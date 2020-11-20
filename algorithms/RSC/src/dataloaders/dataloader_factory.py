from algorithms.RSC.src.dataloaders.PACS_Dataloader import PACSDataloader, PACS_Test_Dataloader
from algorithms.RSC.src.dataloaders.VLCS_Dataloader import VLCSDataloader, VLCS_Test_Dataloader

train_dataloaders_map = {
    'PACS': PACSDataloader,
    'VLCS': VLCSDataloader
}

test_dataloaders_map = {
    'PACS': PACS_Test_Dataloader,
    'VLCS': VLCS_Test_Dataloader
}

def get_train_dataloader(name):
    if name not in train_dataloaders_map:
        raise ValueError('Name of train dataloader unknown %s' % name)

    def get_dataloader_fn(**kwargs):
        return train_dataloaders_map[name](**kwargs)

    return get_dataloader_fn

def get_test_dataloader(name):
    if name not in test_dataloaders_map:
        raise ValueError('Name of test dataloader unknown %s' % name)

    def get_dataloader_fn(**kwargs):
        return test_dataloaders_map[name](**kwargs)

    return get_dataloader_fn