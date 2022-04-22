import torch
import torch.nn as nn 
import yaml
from pathlib import Path

from seg.model.CNN.CNN import CNN_BRANCH
from seg.model.CNN.CNN_backboned import CNN_BRANCH_WITH_BACKBONE
from seg.model.transformer.create_model import create_transformer
from seg.model.Fusion.fuse import SimpleFusion
from .fuse import MiniEncoderFuse

class OldFusionNetwork(nn.Module):
    def __init__(
        self, 
        cnn_model_cfg,
        trans_model_cfg,
        cnn_pretrained=False,
        with_fusion=True,
        with_aspp=False,
        ):
        super(OldFusionNetwork, self).__init__()
        # trans_model_cfg['n_cls'] = 32
        print("cfg", trans_model_cfg)
        
        self.patch_size = cnn_model_cfg['patch_size']
        assert cnn_model_cfg['patch_size'] == trans_model_cfg['patch_size'], \
            'patch_size not configd properly, model_cfgs have different values'
        assert self.patch_size == 16 or self.patch_size == 32, \
            'patch_size must be {16, 32}'
        self.cnn_pretrained = cnn_pretrained
        if self.cnn_pretrained:
            # just a couple checks 
            assert cnn_model_cfg['image_size'][0] == cnn_model_cfg['image_size'][1], \
                'image_height and width must be the same' 
            assert cnn_model_cfg['image_size'][0] == 256 or \
                cnn_model_cfg['image_size'][0] == 512, 'self explanatory'

            self.cnn_branch = CNN_BRANCH_WITH_BACKBONE(
                n_channels=cnn_model_cfg['in_channels'],
                n_classes=cnn_model_cfg['num_classes'],
                patch_size=cnn_model_cfg['patch_size'],
                backbone_name=cnn_model_cfg['backbone'],
                bilinear=True,
                pretrained=self.cnn_pretrained,
                with_fusion=True,
                input_size=cnn_model_cfg['image_size'][0],
            )
        else:
            self.cnn_branch = CNN_BRANCH(
                n_channels=cnn_model_cfg['in_channels'],
                n_classes=cnn_model_cfg['num_classes'],
                patch_size=cnn_model_cfg['patch_size'],
                use_ASPP=with_aspp,
                bilinear=True,
            )
        # now populate dimensions 
        self.cnn_branch.get_dimensions(
            N_in = cnn_model_cfg['batch_size'],
            C_in = cnn_model_cfg['in_channels'],
            H_in = cnn_model_cfg['image_size'][0], 
            W_in = cnn_model_cfg['image_size'][1]
        )

        print(f'Warning in file: {__file__}, we are manually assigning the \
decoder to have a `linear` value in create_transformer when creating the \
fusion network and thus not using the decoder value input to main() in \
train.py, but im too tired to try and figure out how to work that and were \
running the terminal right now so...') # SEE BELOW.... decoder = 'linear'
        # need to do something or pull information from the trans_model_cfg and
        #  pull that info. but yeah. wahtever rn lol 
        self.trans_branch = create_transformer(trans_model_cfg, 
            decoder='linear')
        
        #  adding mini fusion decoder 
        self.trans_branch_fusion = create_transformer(trans_model_cfg, 
            decoder='linear', branch='fusion')

        self.with_fusion = with_fusion
        if self.with_fusion:
            self.fuse_1_2 = MiniEncoderFuse(
                self.cnn_branch.x_1_2.shape[1], 1, 64, 1, stage = '1_2')
            self.fuse_1_4 = MiniEncoderFuse(
                self.cnn_branch.x_1_4.shape[1], 1, 64, 1, stage='1_4')
            self.fuse_1_8 = MiniEncoderFuse(
                self.cnn_branch.x_1_8.shape[1], 1, 64, 1, stage='1_8')
            self.fuse_1_16 = MiniEncoderFuse(
                self.cnn_branch.x_1_16.shape[1], 1, 64, 1, stage='1_16')
            if self.patch_size == 32:
                self.fuse_1_32 = MiniEncoderFuse(
                    self.cnn_branch.x_1_32.shape[1], 1, 64, 1, stage='1_32')

    def forward(self, images):
        x_final_cnn = self.cnn_branch(images)
        x_final_trans = self.trans_branch(images)
        x_final_trans_tmp = self.trans_branch_fusion(images)
        # print("x_final_trans", x_final_trans.shape)
        # print("x_final_cnn", x_final_cnn.shape)
        '''
        self.CNN_BRANCH and self.TRANSFORMER_BRANCH should have same members:
                { output_1_4, output_1_2 }
        '''
        # print("self.cnn_branch.x_1_2:###", self.cnn_branch.x_1_2.shape)
        if self.with_fusion:
            # 1 / 2 - note (kind of wack given that you have to interploate from 1/4)
            x_1_2 = self.fuse_1_2(self.cnn_branch.x_1_2, self.trans_branch_fusion.x_1_2) # x-1_16 : C = 
            # print('i am here transformer')
            x_1_4 = self.fuse_1_4(self.cnn_branch.x_1_4, self.trans_branch_fusion.x_1_4) # x-1_16 : C = 256
            x_1_8 = self.fuse_1_8(self.cnn_branch.x_1_8, self.trans_branch_fusion.x_1_8) # x-1_16 : C = 512
            x_1_16 = self.fuse_1_16(self.cnn_branch.x_1_16, self.trans_branch_fusion.x_1_16) # x-1_16 : C = 512
            # print("self.trans_branch_fusion.x_1_2: ####", self.trans_branch_fusion.x_1_2.shape)
            
            # print('i____m here')

            if self.patch_size == 16:
                tensor_list = [x_final_cnn, x_final_trans, x_1_2, x_1_4, x_1_8, x_1_16]
                mean = torch.mean(torch.stack(tensor_list), dim=0) 
                return mean
            elif self.patch_size == 32:
                x_1_32 = self.fuse_1_32(self.cnn_branch.x_1_32, self.trans_branch.x_1_32)
                tensor_list = [x_final_cnn, x_final_trans, x_1_2, x_1_4, x_1_8, x_1_16, x_1_32]
                mean = torch.mean(torch.stack(tensor_list), dim=0) 
                return mean