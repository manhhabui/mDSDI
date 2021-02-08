import os
import numpy as np
import torch
from matplotlib import pyplot as plt
from sklearn.manifold import TSNE
import pickle

def plot_TNSE(X_2d_tr, tr_labels, label_target_names, filename, title_name, legend = False):
    colors=['red','green','blue','black','brown','grey','orange','yellow','pink','cyan','magenta']
    plt.figure(figsize=(16, 16))
    for i, label in zip(range(len(label_target_names)), label_target_names):
        if label == 0:
            plt.scatter(X_2d_tr[tr_labels == i, 0], X_2d_tr[tr_labels == i, 1], c=colors[i], marker='.', label="dog")
        if label == 1:
            plt.scatter(X_2d_tr[tr_labels == i, 0], X_2d_tr[tr_labels == i, 1], c=colors[i], marker='.', label="elephant")
        if label == 2:
            plt.scatter(X_2d_tr[tr_labels == i, 0], X_2d_tr[tr_labels == i, 1], c=colors[i], marker='.', label="giraffe")
        if label == 3:
            plt.scatter(X_2d_tr[tr_labels == i, 0], X_2d_tr[tr_labels == i, 1], c=colors[i], marker='.', label="guitar")
        if label == 4:
            plt.scatter(X_2d_tr[tr_labels == i, 0], X_2d_tr[tr_labels == i, 1], c=colors[i], marker='.', label="horse")
        if label == 5:
            plt.scatter(X_2d_tr[tr_labels == i, 0], X_2d_tr[tr_labels == i, 1], c=colors[i], marker='.', label="house")
        if label == 6:
            plt.scatter(X_2d_tr[tr_labels == i, 0], X_2d_tr[tr_labels == i, 1], c=colors[i], marker='.', label="person")

    if legend:
        plt.legend(loc=2, fontsize = 'x-small')
    # plt.title(title_name)
    plt.savefig(filename)

def tsne_plot(Zi_out, Zs_out, labels, domain_labels, dir_name):
    def unique(list1):
        unique_list = []
        for x in list1:
            if x not in unique_list:
                unique_list.append(x)
        return unique_list

    Z_out = []
    for idx in range(len(Zi_out)):
        Z_out.append(Zi_out[idx] + Zs_out[idx])

    labels = np.asarray(labels)
    domain_labels = np.asarray(domain_labels)
    label_target_names = unique(labels)
    domain_label_target_names = unique(domain_labels)

    tsne_model = TSNE(n_components=2, init='pca')
    Z_2d = tsne_model.fit_transform(Z_out)
    Zi_2d = tsne_model.fit_transform(Zi_out)
    Zs_2d = tsne_model.fit_transform(Zs_out)
    
    plot_TNSE(Z_2d, labels, label_target_names, dir_name + 'Z_class_tSNE.png', title_name = "DSDI (Classes)", legend = True)
    plot_TNSE(Z_2d, domain_labels, domain_label_target_names, dir_name + 'Z_domain_tSNE.png', title_name = "DSDI (Domains)")

    plot_TNSE(Zi_2d, labels, label_target_names, dir_name + 'Zi_class_tSNE.png', title_name = "DI (Classes)", legend = True)
    plot_TNSE(Zi_2d, domain_labels, domain_label_target_names, dir_name + 'Zi_domain_tSNE.png', title_name = "DI (Domains)")

    plot_TNSE(Zs_2d, labels, label_target_names, dir_name + 'Zs_class_tSNE.png', title_name = "DS (Classes)", legend = True)
    plot_TNSE(Zs_2d, domain_labels, domain_label_target_names, dir_name + 'Zs_domain_tSNE.png', title_name = "DS (Domains)")

def main():
    dir_name = "algorithms/DI_debug/results/plots/PACS_photo_1/"
    with open (dir_name + 'Zi_out.pkl', 'rb') as fp:
        Zi_out = pickle.load(fp)
    with open (dir_name + 'Zi_out.pkl', 'rb') as fp:
        Zs_out = pickle.load(fp)
    with open (dir_name + 'Y_out.pkl', 'rb') as fp:
        Y_out = pickle.load(fp)
    with open (dir_name + 'Y_domain_out.pkl', 'rb') as fp:
        Y_domain_out = pickle.load(fp)
    
    with open (dir_name + 'Zi_test.pkl', 'rb') as fp:
        Zi_test = pickle.load(fp)
    with open (dir_name + 'Zi_test.pkl', 'rb') as fp:
        Zs_test = pickle.load(fp)
    with open (dir_name + 'Y_test.pkl', 'rb') as fp:
        Y_test = pickle.load(fp)
    with open (dir_name + 'Y_domain_test.pkl', 'rb') as fp:
        Y_domain_test = pickle.load(fp)

    for i in range(len(Y_domain_test)):
        Y_domain_test[i] = 3

    Zi_out += Zi_test
    Zs_out += Zs_test
    Y_out += Y_test
    Y_domain_out += Y_domain_test

    tsne_plot(Zi_out, Zs_out, Y_out, Y_domain_out, dir_name)

main()