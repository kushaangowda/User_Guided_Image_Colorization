import torch
import torch.nn as nn
from torch.nn import functional as F
from model.ResUNet import ResUNet
from model.TransUNet import TransUNet
from model.UNet import UNet
from utils.data_loader import create_test_loader
from torch.nn.parallel import DistributedDataParallel as DDP
from tqdm import tqdm
import os
import shutil
import numpy as np
import cv2
from PIL import Image
from skimage import color, io


def dataload(file_path,batch_size,n_w):
    test_loader = create_test_loader(file_path, batch_size=batch_size, test_size=0.2, 
                                                random_seed=42, n_w=n_w)
    return test_loader

def setup(in_channels,out_channels,n_layers=5,bn_layers=2,num_bins=40,model_path=None,model_type=1):
    assert len(in_channels) == n_layers and len(out_channels) == n_layers, \
    'Error: channels should be same as number of layers'
    if model_type == 0:
        print("Using simple UNet")
        model = UNet(in_channels=in_channels,out_channels=out_channels,
                        blocks=n_layers,bn_blocks=bn_layers,num_bins=num_bins)
    elif model_type == 1:
        print("Using ResUNet")
        model = ResUNet(in_channels=in_channels,out_channels=out_channels,
                blocks=n_layers,bn_blocks=bn_layers,num_bins=num_bins)
    else:
        print("Using TransUNet")
        model = TransUNet(in_channels=in_channels,out_channels=out_channels,
                blocks=n_layers,bn_blocks=bn_layers,num_bins=num_bins)
                    
    if model_path is not None:
        try:
            model.load_state_dict(torch.load(model_path))
        except:
            print("Couldn't load model weights")

    return model

def pixelwise_accuracy(output, target):
    _, predicted = torch.max(output, 1)
    correct = (predicted == target).float()
    return correct.mean()

def unbin(arr, num_bins):
    bs, h, w = arr.shape
    arr1 = torch.ones_like(arr)
    arr1 = -128 + (128/num_bins) + arr*(256/num_bins)
    return arr1

def save_img(images, labels, outputs, idx, num_bins):
    orig_gray = images[:,0,:,:].cpu().numpy()*100
    orig_a = unbin(labels[:,0,:,:], num_bins).cpu().numpy()
    orig_b = unbin(labels[:,1,:,:], num_bins).cpu().numpy()

    _, pred_a = torch.max(outputs[:,0,:,:,:], 1)
    _, pred_b = torch.max(outputs[:,1,:,:,:], 1)
    
    pred_a = unbin(pred_a, num_bins).cpu().numpy()
    pred_b = unbin(pred_b, num_bins).cpu().numpy()

    for i in range(len(images)):
        orig_lab_image = np.stack([orig_gray[i], orig_a[i], orig_b[i]], axis=-1).astype(np.float32)
        rgb_image = color.lab2rgb(orig_lab_image)
        rgb_image = (rgb_image * 255).astype(np.uint8)
        image_path = os.path.join("predictions", f'image_orig_{idx}.png')
        io.imsave(image_path, rgb_image)
        
        pred_lab_image = np.stack([orig_gray[i], pred_a[i], pred_b[i]], axis=-1).astype(np.float32)
        rgb_image = color.lab2rgb(pred_lab_image)
        rgb_image = (rgb_image * 255).astype(np.uint8)
        image_path = os.path.join("predictions", f'image_pred_{idx}.png')
        io.imsave(image_path, rgb_image)

    

def predict(test_loader,model,device,top_k=5,num_batches=None,num_bins=40):
    if os.path.exists("predictions"):
        shutil.rmtree("predictions")
    os.mkdir("predictions")

    print(f"Using device {device}")

    if num_batches is None:
        num_batches = len(test_loader)

    test_iterator = iter(test_loader)

    for i in  range(num_batches):
        images,labels = next(test_iterator)
            
        model.eval()
        # Move tensors to configured device
        images = images.to(device)
        images = images[:,:-1]
        labels = labels.to(device).long()
        labels = torch.clamp(labels, 0, num_bins-1)

        masks = images[:,-1].type(torch.bool)

        masked_labels_0 = labels[:,0].clone()
        masked_labels_0[~masks] = -1 
        masked_labels_1 = labels[:,1].clone()
        masked_labels_1[~masks] = -1 
        
        # Calculate accuracy
        outputs = model(images)

        save_img(images, labels, outputs, i, num_bins)