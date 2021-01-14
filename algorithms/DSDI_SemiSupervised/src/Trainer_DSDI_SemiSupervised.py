import os
import logging
import shutil
import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter

from algorithms.DSDI_SemiSupervised.src.dataloaders import dataloader_factory
from algorithms.DSDI_SemiSupervised.src.models import model_factory
from torch.optim import lr_scheduler
from torch.optim.lr_scheduler import StepLR
import matplotlib.pyplot as plt
import torchvision
import copy
import torch.autograd as autograd
from sklearn.manifold import TSNE

class GradReverse(torch.autograd.Function):
    iter_num = 0
    alpha = 10
    low = 0.0
    high = 1.0
    max_iter = 3000

    @staticmethod
    def forward(ctx, x):
        GradReverse.iter_num += 1
        return x.view_as(x)

    @staticmethod
    def backward(ctx, grad_output):
        coeff = np.float(2.0 * (GradReverse.high - GradReverse.low) / (1.0 + np.exp(-GradReverse.alpha * GradReverse.iter_num / GradReverse.max_iter))
                         - (GradReverse.high - GradReverse.low) + GradReverse.low)
        return -coeff * grad_output

class Domain_Discriminator(nn.Module):
    def __init__(self, feature_dim, domain_classes):
        super(Domain_Discriminator, self).__init__()
        self.class_classifier = nn.Sequential(
            nn.Linear(feature_dim, feature_dim),
            nn.ReLU(),
            nn.Linear(feature_dim, domain_classes)
        )

    def forward(self, di_z):
        y = self.class_classifier(GradReverse.apply(di_z))
        return y

class Classifier(nn.Module):
    def __init__(self, feature_dim, classes):
        super(Classifier, self).__init__()
        self.classifier = nn.Linear(int(feature_dim * 2), classes)
    
    def forward(self, di_z, ds_z):
        z = torch.cat((di_z, ds_z), dim = 1)
        y = self.classifier(z)
        return y 

class ZS_Domain_Classifier(nn.Module):
    def __init__(self, feature_dim, domain_classes):
        super(ZS_Domain_Classifier, self).__init__()
        self.class_classifier = nn.Sequential(
            nn.Linear(feature_dim, domain_classes)
        )

    def forward(self, ds_z):
        y = self.class_classifier(ds_z)
        return y

invTrans = torchvision.transforms.Compose([ torchvision.transforms.Normalize(mean = [ 0., 0., 0. ],
                                                     std = [ 1/0.229, 1/0.224, 1/0.225 ]),
                                torchvision.transforms.Normalize(mean = [ -0.485, -0.456, -0.406 ],
                                                     std = [ 1., 1., 1. ]),
                               ])

def random_pairs_of_minibatches(samples, labels):
    perm = torch.randperm(len(samples)).tolist()
    pairs = []

    for j in range(len(samples)):
        xi, yi = [], []
        for i in range(len(samples)):
            if i != j:
                xi += samples[perm[i]]
                yi += labels[perm[i]]
        
        xi = torch.stack(xi)
        yi = torch.stack(yi)
        xj, yj = samples[perm[j]], labels[perm[j]]

        pairs.append(((xi, yi), (xj, yj)))

    return pairs

def set_tr_val_samples_labels(meta_filenames):
    sample_tr_paths, class_tr_labels, sample_val_paths, class_val_labels = [], [], [], []
    un_sample_tr_paths = []
    for idx_domain, meta_filename in enumerate(meta_filenames):
        column_names = ['filename', 'class_label']
        data_frame = pd.read_csv(meta_filename, header = None, names = column_names, sep='\s+')
        data_frame = data_frame.sample(frac=1).reset_index(drop=True)

        split_idx = int(len(data_frame) * 0.8)
        sample_tr_paths.append(data_frame["filename"][:split_idx])
        class_tr_labels.append(data_frame["class_label"][:split_idx])

        sample_val_paths.extend(data_frame["filename"][split_idx:])
        class_val_labels.extend(data_frame["class_label"][split_idx:])
    
    for idx_domain in range(len(sample_tr_paths)):
        un_split_idx = int(len(sample_tr_paths[idx_domain]) * 0.1)
        un_sample_tr_paths.append(sample_tr_paths[idx_domain][un_split_idx:])
        sample_tr_paths[idx_domain] = sample_tr_paths[idx_domain][:un_split_idx]
        class_tr_labels[idx_domain] = class_tr_labels[idx_domain][:un_split_idx]

    return un_sample_tr_paths, sample_tr_paths, class_tr_labels, sample_val_paths, class_val_labels

def set_test_samples_labels(meta_filenames):
    sample_paths, class_labels = [], []
    for idx_domain, meta_filename in enumerate(meta_filenames):
        column_names = ['filename', 'class_label']
        data_frame = pd.read_csv(meta_filename, header = None, names = column_names, sep='\s+')
        sample_paths.extend(data_frame["filename"])
        class_labels.extend(data_frame["class_label"])
            
    return sample_paths, class_labels
    
class Trainer_DSDI_SemiSupervised:
    def __init__(self, args, device, exp_idx):
        self.args = args
        self.device = device
        self.writer = self.set_writer(log_dir = "algorithms/" + self.args.algorithm + "/results/tensorboards/" + self.args.exp_name + "_" + exp_idx + "/")
        self.plot_writer = self.set_plot_writer(log_dir = "algorithms/" + self.args.algorithm + "/results/plots/" + self.args.exp_name + "_" + exp_idx + "/")
        un_sample_tr_paths, src_tr_sample_paths, src_tr_class_labels, src_val_sample_paths, src_val_class_labels = set_tr_val_samples_labels(self.args.src_train_meta_filenames)
        test_sample_paths, test_class_labels = set_test_samples_labels(self.args.target_test_meta_filenames)

        self.train_loaders = [DataLoader(dataloader_factory.get_train_dataloader(self.args.dataset)(src_path = self.args.src_data_path, sample_paths = src_tr_sample_paths[0], class_labels = src_tr_class_labels[0], domain_label = 0), batch_size = self.args.batch_size, shuffle = True),
            DataLoader(dataloader_factory.get_train_dataloader(self.args.dataset)(src_path = self.args.src_data_path, sample_paths = src_tr_sample_paths[1], class_labels = src_tr_class_labels[1], domain_label = 1), batch_size = self.args.batch_size, shuffle = True),
            DataLoader(dataloader_factory.get_train_dataloader(self.args.dataset)(src_path = self.args.src_data_path, sample_paths = src_tr_sample_paths[2], class_labels = src_tr_class_labels[2], domain_label = 2), batch_size = self.args.batch_size, shuffle = True)]
        self.un_train_loaders = [DataLoader(dataloader_factory.get_train_dataloader(self.args.dataset)(src_path = self.args.src_data_path, sample_paths = un_sample_tr_paths[0], class_labels = -1, domain_label = 0), batch_size = self.args.batch_size, shuffle = True),
            DataLoader(dataloader_factory.get_train_dataloader(self.args.dataset)(src_path = self.args.src_data_path, sample_paths = un_sample_tr_paths[1], class_labels = -1, domain_label = 1), batch_size = self.args.batch_size, shuffle = True),
            DataLoader(dataloader_factory.get_train_dataloader(self.args.dataset)(src_path = self.args.src_data_path, sample_paths = un_sample_tr_paths[2], class_labels = -1, domain_label = 2), batch_size = self.args.batch_size, shuffle = True)]
        
        self.val_loader = DataLoader(dataloader_factory.get_test_dataloader(self.args.dataset)(src_path = self.args.src_data_path, sample_paths = src_val_sample_paths, class_labels = src_val_class_labels), batch_size = self.args.batch_size, shuffle = True)
        self.test_loader = DataLoader(dataloader_factory.get_test_dataloader(self.args.dataset)(src_path = self.args.src_data_path, sample_paths = test_sample_paths, class_labels = test_class_labels), batch_size = self.args.batch_size, shuffle = True)

        self.model = model_factory.get_model(self.args.model)().to(self.device)
        self.classifier = Classifier(feature_dim = self.args.feature_dim, classes = self.args.n_classes).to(self.device)
        self.zs_domain_classifier = ZS_Domain_Classifier(feature_dim = self.args.feature_dim, domain_classes = 3).to(self.device)
        self.domain_discriminator = Domain_Discriminator(feature_dim = self.args.feature_dim, domain_classes = 3).to(self.device)

        optimizer = list(self.model.parameters()) + list(self.classifier.parameters()) + list(self.domain_discriminator.parameters()) + list(self.zs_domain_classifier.parameters())
        self.optimizer = torch.optim.SGD(optimizer, lr = self.args.learning_rate, weight_decay = self.args.weight_decay, momentum = self.args.momentum, nesterov = False)

        self.criterion = nn.CrossEntropyLoss()
        self.reconstruction_criterion = nn.MSELoss()
        self.scheduler = StepLR(self.optimizer, step_size=self.args.iterations * 0.8)

        self.checkpoint_name = "algorithms/" + self.args.algorithm + "/results/checkpoints/" + self.args.exp_name + "_" + exp_idx
        self.val_loss_min = np.Inf

    def set_writer(self, log_dir):
        if not os.path.exists(log_dir):
            os.mkdir(log_dir)
        shutil.rmtree(log_dir)
        return SummaryWriter(log_dir)

    def set_plot_writer(self, log_dir):
        if not os.path.exists(log_dir):
            os.mkdir(log_dir)

        return log_dir

    def train(self):
        checkpoint = torch.load(self.checkpoint_name + '.pt')
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.classifier.load_state_dict(checkpoint['classifier_state_dict'])
        self.zs_domain_classifier.load_state_dict(checkpoint['zs_domain_classifier_state_dict'])
        self.domain_discriminator.load_state_dict(checkpoint['domain_discriminator_state_dict'])
        # self.disentangle_discriminator.load_state_dict(checkpoint['disentangle_discriminator_state_dict'])

        self.model.eval()
        self.classifier.eval()
        self.zs_domain_classifier.eval()
        self.domain_discriminator.eval()
        # self.disentangle_discriminator.eval()

        Zi_out, Zs_out, Y_out, Y_domain_out = [], [], [], []

        with torch.no_grad():
            self.train_iter_loaders = []
            for train_loader in self.train_loaders:
                self.train_iter_loaders.append(iter(train_loader))

            for iteration in range(self.args.iterations):
                samples, labels, domain_labels = [], [], []

                for idx in range(len(self.train_iter_loaders)):
                    if (iteration % len(self.train_iter_loaders[idx])) == 0:
                        self.train_iter_loaders[idx] = iter(self.train_loaders[idx])
                    train_loader = self.train_iter_loaders[idx]

                    itr_samples, itr_labels, itr_domain_labels = train_loader.next()

                    samples.append(itr_samples)
                    labels.append(itr_labels)
                    domain_labels.append(itr_domain_labels)     

                samples = torch.cat(samples, dim=0).to(self.device)
                labels = torch.cat(labels, dim=0).to(self.device)
                domain_labels = torch.cat(domain_labels, dim=0).to(self.device) 
                di_z, ds_z, x_hat = self.model(samples)

                Zi_out += di_z.tolist()
                Zs_out += ds_z.tolist()   
                Y_out += labels.tolist() 
                Y_domain_out += domain_labels.tolist()
        
        tsne_model = TSNE(n_components=2, init='pca')
        Zi_out = tsne_model.fit_transform(Zi_out)
        Zs_out = tsne_model.fit_transform(Zs_out)
        print(Zi_out[0])
        exit()

    def train_2(self):
        self.model.train()
        self.classifier.train()
        self.zs_domain_classifier.train()
        self.domain_discriminator.train()

        n_class_corrected = 0
        n_domain_class_corrected = 0
        n_zs_domain_class_corrected = 0

        total_classification_loss = 0
        total_dc_loss = 0
        total_zsc_loss = 0
        total_disentangle_loss = 0
        total_reconstruction_loss = 0
        total_samples = 0
        total_meta_samples = 0
        self.train_iter_loaders = []
        for train_loader in self.train_loaders:
            self.train_iter_loaders.append(iter(train_loader))

        self.un_train_iter_loaders = []
        for train_loader in self.un_train_loaders:
            self.un_train_iter_loaders.append(iter(train_loader))

        for iteration in range(self.args.iterations):       
            self.optimizer.zero_grad()
            self_param = list(self.model.ds_encoder.parameters()) + list(self.classifier.parameters())
            for p in self_param:
                if p.grad is None:
                    p.grad = torch.zeros_like(p)

            un_samples, samples, labels, un_samples_domain_labels, domain_labels = [], [], [], [], []

            for idx in range(len(self.train_iter_loaders)):
                if (iteration % len(self.train_iter_loaders[idx])) == 0:
                    self.train_iter_loaders[idx] = iter(self.train_loaders[idx])
                train_loader = self.train_iter_loaders[idx]
                
                itr_samples, itr_labels, itr_domain_labels = train_loader.next()

                samples.append(itr_samples)
                labels.append(itr_labels)
                domain_labels.append(itr_domain_labels)

            for idx in range(len(self.un_train_iter_loaders)):
                if (iteration % len(self.un_train_iter_loaders[idx])) == 0:
                    self.un_train_iter_loaders[idx] = iter(self.train_loaders[idx])
                train_loader = self.un_train_iter_loaders[idx]
                
                itr_samples, _, itr_domain_labels = train_loader.next()

                un_samples.append(itr_samples)
                un_samples_domain_labels.append(itr_domain_labels)

            for (mtr_samples, mtr_labels), (mte_samples, mte_labels) in random_pairs_of_minibatches(samples, labels):
                mtr_samples = mtr_samples.to(self.device)
                mtr_labels = mtr_labels.to(self.device)
                mte_samples = mte_samples.to(self.device)
                mte_labels = mte_labels.to(self.device)

                inner_model = copy.deepcopy(self.model)
                inner_classifier = copy.deepcopy(self.classifier)
                    
                inner_param = list(inner_model.ds_encoder.parameters()) + list(inner_classifier.parameters())
                lr_rate = self.args.learning_rate
                if iteration > int(self.args.iterations * 0.8):
                    lr_rate *= 0.1
                inner_opt = torch.optim.SGD(inner_param, lr = lr_rate, weight_decay = self.args.weight_decay, momentum = self.args.momentum, nesterov = False)

                di_z, ds_z, x_hat = inner_model(mtr_samples)
                predicted_classes = inner_classifier(di_z, ds_z)
                inner_obj = self.criterion(predicted_classes, mtr_labels)
                _, predicted_classes = torch.max(predicted_classes, 1)
                n_class_corrected += (predicted_classes == mtr_labels).sum().item()

                inner_opt.zero_grad()
                inner_obj.backward()
                inner_opt.step()

                for p_tgt, p_src in zip(self_param, inner_param):
                    if p_src.grad is not None:
                        p_tgt.grad.data.add_(p_src.grad.data / 3)
                        
                total_classification_loss += inner_obj.item()

                # this computes Gj on the clone-network
                di_z, ds_z, x_hat = inner_model(mte_samples)
                predicted_classes = inner_classifier(di_z, ds_z)
                loss_inner_j = self.criterion(predicted_classes, mte_labels)
                _, predicted_classes = torch.max(predicted_classes, 1)
                n_class_corrected += (predicted_classes == mte_labels).sum().item()

                grad_inner_j = autograd.grad(loss_inner_j, inner_param,
                    allow_unused=True)

                # `objective` is populated for reporting purposes
                total_classification_loss += (1.0 * loss_inner_j).item()

                for p, g_j in zip(self_param, grad_inner_j):
                    if g_j is not None:
                        p.grad.data.add_(1.0 * g_j.data / 3)  

                total_meta_samples += len(mtr_samples)
                total_meta_samples += len(mte_samples)              

            samples = torch.cat(samples, dim=0)
            un_samples = torch.cat(un_samples, dim=0)
            domain_labels = torch.cat(domain_labels, dim=0)
            un_samples_domain_labels = torch.cat(un_samples_domain_labels, dim=0)
            lb_samples = samples.to(self.device)
            lb_labels = torch.cat(labels, dim=0).to(self.device)
            samples = torch.cat((samples, un_samples), 0).to(self.device)
            domain_labels = torch.cat((domain_labels, un_samples_domain_labels), 0).to(self.device)

            di_z, ds_z, x_hat = self.model(lb_samples)
            predicted_classes = self.classifier(di_z, ds_z)
            classification_loss = self.criterion(predicted_classes, lb_labels)
            total_classification_loss += classification_loss.item()
            _, predicted_classes = torch.max(predicted_classes, 1)
            n_class_corrected += (predicted_classes == lb_labels).sum().item()

            di_z, ds_z, x_hat = self.model(samples)

            # Correlation Matrix
            mdi_z = torch.mean(di_z, 0)         # Size M
            mds_z = torch.mean(ds_z, 0)           # Size N

            di_z_n = (di_z - mdi_z[None, :])           # BxM
            ds_z_n = (ds_z - mds_z[None, :])           # BxN
            C = di_z_n[:, :, None] * ds_z_n[:,None,:]              # BxMxN
            
            target_cr = torch.zeros(C.shape[0], C.shape[1], C.shape[2]).to(self.device)
            disentangle_loss = nn.MSELoss()(C, target_cr)
            total_disentangle_loss += disentangle_loss.item()

            di_predicted_domain = self.domain_discriminator(di_z)
            predicted_domain_di_loss = self.criterion(di_predicted_domain, domain_labels)
            total_dc_loss += predicted_domain_di_loss.item()

            ds_predicted_classes = self.zs_domain_classifier(ds_z)
            predicted_domain_ds_loss = self.criterion(ds_predicted_classes, domain_labels)
            total_zsc_loss += predicted_domain_ds_loss.item()

            reconstruction_loss = self.reconstruction_criterion(x_hat, samples)
            total_reconstruction_loss += reconstruction_loss.item()

            total_loss = classification_loss
            # total_loss = classification_loss + predicted_domain_di_loss + predicted_domain_ds_loss + disentangle_loss + reconstruction_loss

            _, ds_predicted_classes = torch.max(ds_predicted_classes, 1)
            n_zs_domain_class_corrected += (ds_predicted_classes == domain_labels).sum().item()
            _, di_predicted_domain = torch.max(di_predicted_domain, 1)
            n_domain_class_corrected += (di_predicted_domain == domain_labels).sum().item()

            total_samples += len(samples)
            total_class_samples = len(lb_samples) + total_meta_samples

            total_loss.backward()
            self.optimizer.step()
            self.scheduler.step()

            if iteration % self.args.step_eval == 0:
                self.writer.add_scalar('Accuracy/train', 100. * n_class_corrected / total_class_samples, iteration)
                self.writer.add_scalar('Accuracy/domainAT_train', 100. * n_domain_class_corrected / total_samples, iteration)
                self.writer.add_scalar('Accuracy/domainZS_train', 100. * n_zs_domain_class_corrected / total_samples, iteration)
                self.writer.add_scalar('Loss/train', total_classification_loss / total_class_samples, iteration)
                self.writer.add_scalar('Loss/domainAT_train', total_dc_loss / total_samples, iteration)
                self.writer.add_scalar('Loss/domainZS_train', total_zsc_loss / total_samples, iteration)
                self.writer.add_scalar('Loss/disentangle', total_disentangle_loss / total_samples, iteration)
                self.writer.add_scalar('Loss/reconstruction', total_reconstruction_loss / total_samples, iteration)
                logging.info('Train set: Iteration: [{}/{}]\tAccuracy: {}/{} ({:.2f}%)\tLoss: {:.6f}'.format(iteration, self.args.iterations,
                    n_class_corrected, total_class_samples, 100. * n_class_corrected / total_class_samples, total_classification_loss / total_class_samples))
                self.evaluate(iteration)

                if len(samples) > 49:
                    for i in range(49):
                        # define subplot
                        plt.subplot(7, 7, 1 + i)
                        # turn off axis
                        plt.axis('off')
                        # plot raw pixel data
                        plt.imshow((invTrans(samples[i]).detach().cpu().numpy().transpose((1, 2, 0)) * 255).astype(np.uint8))

                    plt.savefig(self.plot_writer + "IMAGE_{}.png".format(iteration), bbox_inches='tight', dpi=600)

                    for i in range(49):
                        # define subplot
                        plt.subplot(7, 7, 1 + i)
                        # turn off axis
                        plt.axis('off')
                        # plot raw pixel data
                        plt.imshow((invTrans(x_hat[i]).detach().cpu().numpy().transpose((1, 2, 0)) * 255).astype(np.uint8))

                    plt.savefig(self.plot_writer + "GEN_IMAGE_{}.png".format(iteration), bbox_inches='tight', dpi=600)
                
                n_class_corrected = 0
                n_domain_class_corrected = 0
                n_zs_domain_class_corrected = 0

                total_dc_loss = 0
                total_classification_loss = 0
                total_zsc_loss = 0
                total_disentangle_loss = 0
                total_reconstruction_loss = 0
                total_samples = 0
                total_meta_samples = 0
    
    def evaluate(self, n_iter):
        self.model.eval()
        self.classifier.eval()
        self.zs_domain_classifier.eval()
        self.domain_discriminator.eval()

        n_class_corrected = 0
        total_classification_loss = 0
        with torch.no_grad():
            for iteration, (samples, labels, domain_labels) in enumerate(self.val_loader):
                samples, labels, domain_labels = samples.to(self.device), labels.to(self.device), domain_labels.to(self.device)
                di_z, ds_z, x_hat = self.model(samples)

                predicted_classes = self.classifier(di_z, ds_z)

                classification_loss = self.criterion(predicted_classes, labels)
                total_classification_loss += classification_loss.item()

                _, predicted_classes = torch.max(predicted_classes, 1)
                n_class_corrected += (predicted_classes == labels).sum().item()
        
        self.writer.add_scalar('Accuracy/validate', 100. * n_class_corrected / len(self.val_loader.dataset), n_iter)
        self.writer.add_scalar('Loss/validate', total_classification_loss / len(self.val_loader.dataset), n_iter)
        logging.info('Val set: Accuracy: {}/{} ({:.2f}%)\tLoss: {:.6f}'.format(n_class_corrected, len(self.val_loader.dataset),
            100. * n_class_corrected / len(self.val_loader.dataset), total_classification_loss / len(self.val_loader.dataset)))

        val_loss = total_classification_loss / len(self.val_loader.dataset)
        self.model.train()
        # self.model.bn_eval()
        self.classifier.train()
        self.zs_domain_classifier.train()
        self.domain_discriminator.train()

        if self.val_loss_min > val_loss:
            self.val_loss_min = val_loss
            torch.save({'model_state_dict': self.model.state_dict(),
                'classifier_state_dict': self.classifier.state_dict(),
                'zs_domain_classifier_state_dict': self.zs_domain_classifier.state_dict(),
                'domain_discriminator_state_dict': self.domain_discriminator.state_dict(),
                # 'disentangle_discriminator_state_dict': self.disentangle_discriminator.state_dict()
                }, self.checkpoint_name + '.pt')
    
    def test(self):
        checkpoint = torch.load(self.checkpoint_name + '.pt')
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.classifier.load_state_dict(checkpoint['classifier_state_dict'])
        self.zs_domain_classifier.load_state_dict(checkpoint['zs_domain_classifier_state_dict'])
        self.domain_discriminator.load_state_dict(checkpoint['domain_discriminator_state_dict'])
        # self.disentangle_discriminator.load_state_dict(checkpoint['disentangle_discriminator_state_dict'])

        self.model.eval()
        self.classifier.eval()
        self.zs_domain_classifier.eval()
        self.domain_discriminator.eval()
        # self.disentangle_discriminator.eval()

        n_class_corrected = 0
        with torch.no_grad():
            for iteration, (samples, labels, domain_labels) in enumerate(self.test_loader):
                samples, labels, domain_labels = samples.to(self.device), labels.to(self.device), domain_labels.to(self.device)
                di_z, ds_z, x_hat = self.model(samples)
                
                predicted_classes = self.classifier(di_z, ds_z)

                _, predicted_classes = torch.max(predicted_classes, 1)
                n_class_corrected += (predicted_classes == labels).sum().item()
        
        logging.info('Test set: Accuracy: {}/{} ({:.2f}%)'.format(n_class_corrected, len(self.test_loader.dataset), 
            100. * n_class_corrected / len(self.test_loader.dataset)))