import pandas as pd
from torch.utils.data import Dataset
from PIL import Image
import torchvision.transforms as transforms

class MNISTDataloader(Dataset):
    def __init__(self, src_path, sample_paths, class_labels):
        self.image_transformer = transforms.Compose([
            transforms.Resize((28, 28)),
            transforms.ToTensor(),
            transforms.Normalize([0.1307], [0.3081]),
        ])
        self.src_path = src_path
        self.sample_paths, self.class_labels = sample_paths, class_labels
        
    def get_image(self, sample_path):
        img = Image.open(sample_path)
        return self.image_transformer(img)

    def __len__(self):
        return len(self.sample_paths)

    def __getitem__(self, index):
        sample = self.get_image(self.src_path + self.sample_paths[index])
        class_label = self.class_labels[index]
        
        return sample, class_label

class MNIST_Test_Dataloader(MNISTDataloader):
    def __init__(self, *args, **xargs):
        super().__init__(*args, **xargs)
        self.image_transformer = transforms.Compose([
            transforms.Resize((28, 28)),
            transforms.ToTensor(),
            transforms.Normalize([0.1307], [0.3081]),
        ])