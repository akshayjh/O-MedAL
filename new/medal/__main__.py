import glob
import multiprocessing as mp
import numpy as np
from os.path import join, dirname, abspath
import os
import torch
import torch.optim
import torch.utils.data as TD
import torchvision.transforms as tvt
import torchvision as tv

from . import datasets
from . import models


def get_data_loaders(config):
    for idxs in config.dataset.train_test_split(
            train_frac=config.train_frac,
            random_state=config.data_loader_random_state):
        loader = TD.DataLoader(
            config.dataset,
            batch_size=config.batch_size,
            sampler=TD.SubsetRandomSampler(idxs),
            pin_memory=False, num_workers=config.data_loader_num_workers
        )
        yield loader


def save_checkpoint(config, model, optimizer, epoch):
    save_fp = config.checkpoint_fp_template.format(
        run_id=config.run_id, epoch=epoch)
    os.makedirs(dirname(save_fp), exist_ok=True)
    print("Save checkpoint", save_fp)
    torch.save({
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
    }, save_fp)


def load_checkpoint(config):
    model = config.model_class(config)
    model.set_layers_trainable()
    optimizer = torch.optim.Adam(
        model.parameters(), lr=config.learning_rate,
        weight_decay=config.weight_decay, betas=(.95, .999))
    model.to(config.device)

    read_fp = config.checkpoint_fp_template.format(
        run_id=config.run_id, epoch='*')
    fps = glob.glob(read_fp)
    if fps:  # yay - there is a checkpoint to restore
        fp = max(fps)
        print("Restoring from checkpoint:", fp)
        checkpoint = torch.load(fp)
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        epoch = checkpoint['epoch']
    else:
        epoch = 1
    return model, optimizer, epoch


def train_one_epoch(epoch, config, train_loader, model, optimizer):
    #  print('train one epoch')  # TODO remove
    model.train()
    train_loss, train_correct, N = 0, 0, 0
    for batch_idx, (X, y) in enumerate(train_loader):
        if X.shape[0] != config.batch_size:
            #  print("Skipping end of batch", X.shape)
            continue
        X, y = X.to(config.device), y.to(config.device)
        optimizer.zero_grad()
        yhat = model(X)
        loss = model.lossfn(yhat, y.float())
        loss.backward()
        optimizer.step()

        with torch.no_grad():
            batch_size = X.shape[0]
            _loss = loss.item() * batch_size
            train_loss += _loss
            _correct = y.int().eq((yhat.view_as(y) >.5).int()).sum().item()
            train_correct += _correct
            N += batch_size

            # print output if batch_idx % config.log_interval == 0
            if batch_idx % 10 == 0:
                print('-->', 'epoch:', epoch,
                    '\tbatch_idx', batch_idx,
                    '\ttrain_loss:', train_loss/N,
                    '\ttrain_acc', train_correct / N)
    return train_loss/N, train_correct/N


def train(config, train_loader, val_loader, model, optimizer, epoch):
    for epoch in range(epoch, config.epochs + 1):
        train_loss, train_acc = train_one_epoch(
            epoch, config, train_loader, model, optimizer)
        #  save_checkpoint(config, model, optimizer, epoch)
        val_loss, val_acc = test(config, val_loader, model)
        print(
            "epoch", epoch, "train_loss", train_loss, "\tval_loss", val_loss,
            "\ttrain_acc", train_acc, "\tval_acc", val_acc)


def test(config, val_loader, model):
    """Return avg loss and accuracy on the validation data"""
    #  print('test on validation set')  # TODO remove
    model.eval()
    totloss = 0
    correct = 0
    N = 0
    with torch.no_grad():
        for X, y in val_loader:
            batch_size = X.shape[0]
            X, y = X.to(config.device), y.to(config.device)
            yhat = model(X)
            totloss += (model.lossfn(yhat, y.float()) * batch_size).item()
            correct += y.int().eq((yhat.view_as(y) >.5).int()).sum().item()
            N += batch_size
    return totloss/N, correct/N


def main(config):
    # define the dataset
    print('\n'.join(str((k, v)) for k, v in config.__dict__.items()
                    if not k.startswith('__')))
    train_loader, val_loader = get_data_loaders(config)
    model, optimizer, epoch = load_checkpoint(config)
    train(config, train_loader, val_loader, model, optimizer, epoch)


if __name__ == "__main__":
    DATA_DIR = join(dirname(dirname(abspath(__file__))), 'data')

    class config:
        run_id = "baseline_inception3"
        model_class = models.MedALInceptionV3
        epochs = 100
        batch_size = 16
        #  batch_size = 64  # TODO
        learning_rate = 1e-3  # TODO
        data_loader_num_workers = max(1, mp.cpu_count() - 2)
        train_frac = .3  # TODO
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        weight_decay = 0.01

        data_loader_random_state = 0  # np.random.RandomState(0)
        model_dir = join(DATA_DIR, "torch/models")
        checkpoint_fp_template = join(
            DATA_DIR, "model_checkpoints/{run_id}/epoch_{epoch}.pth")

        dataset = datasets.Messidor(
            join(DATA_DIR, "messidor/*.csv"),
            join(DATA_DIR, "messidor/**/*.tif"),
            img_transform=tvt.Compose([
                tvt.RandomCrop((512, 512)),
                tvt.ToTensor(),
            ]),
            getitem_transform=lambda x: (
                x['image'],
                torch.tensor([float(x['Retinopathy grade'] != 0)]))
        )

        def __repr__(self):
            return "config:%s" % self.run_id

    main(config)
