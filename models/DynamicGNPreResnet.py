import torch
import torch.nn as nn
from models.dynamic_conv2d import DynamicConvGN2d
import math

class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, inplanes, planes, num_groups=2, stride=1, downsample=None, preact='no_preact'):
        super(BasicBlock, self).__init__()

        self.bn1 = nn.BatchNorm2d(inplanes)
        self.conv1 = DynamicConvGN2d(num_groups, inplanes, planes, kernel_size=3, stride=stride,
                     padding=1, bias=False)
        self.conv2 = DynamicConvGN2d(num_groups, planes, planes, kernel_size=3, stride=stride,
                     padding=1, bias=False)
        self.relu = nn.ReLU(inplace=True)

        self.downsample = downsample
        self.stride = stride
        self.preact = preact

    def forward(self, input):
        # wrap input/output due to nn.Sequential
        x, keep_rate = input
        residual = x

        out = self.bn1(x)
        out = self.relu(out)

        if self.downsample is not None:
            if self.preact == 'preact':
                residual = self.downsample(out)
            else:
                residual = self.downsample(x)

        out = self.conv1(out, keep_rate)
        out = self.relu(out)
        out = self.conv2(out, keep_rate)

        out += residual

        return (out, keep_rate)

class Bottleneck(nn.Module):
    expansion = 4

    def __init__(self, inplanes, planes, num_groups=2, stride=1, downsample=None, preact='no_preact'):
        super(Bottleneck, self).__init__()

        self.bn1 = nn.BatchNorm2d(inplanes)
        self.conv1 = DynamicConvGN2d(num_groups, inplanes, planes, kernel_size=1, bias=False)
        self.conv2 = DynamicConvGN2d(num_groups, planes, planes, kernel_size=3, stride=stride, padding=1, bias=False)
        self.conv3 = DynamicConvGN2d(num_groups, planes, planes * Bottleneck.expansion, kernel_size=1, bias=False)
        self.relu = nn.ReLU(inplace=True)

        self.downsample = downsample
        self.stride = stride
        self.preact = preact

    def forward(self, input):
        # wrap input/output due to nn.Sequential
        x, keep_rate = input
        residual = x

        out = self.bn1(x)
        out = self.relu(out)

        if self.downsample is not None:
            if self.preact == 'preact':
                residual = self.downsample(out)
            else:
                residual = self.downsample(x)

        out = self.conv1(out, keep_rate)
        out = self.relu(out)
        out = self.conv2(out, keep_rate)
        out = self.relu(out)
        out = self.conv3(out, keep_rate)

        out += residual

        return (out, keep_rate)


class DynamicGNPreResNet(nn.Module):
    def __init__(self, dataset, depth, num_classes, num_groups=2, bottleneck=True):
        super(DynamicGNPreResNet, self).__init__()
        self.dataset = dataset
        if self.dataset.startswith('cifar'):
            self.inplanes = 16
            if bottleneck == True:
                n = int((depth - 2) / 9)
                block = Bottleneck
            else:
                n = int((depth - 2) / 6)
                block = BasicBlock

            self.conv1 = nn.Conv2d(3, self.inplanes, kernel_size=3, stride=1, padding=1, bias=False)
            self.layer1 = self._make_layer(block, 16, n, num_groups=num_groups)
            self.layer2 = self._make_layer(block, 32, n, stride=2, num_groups=num_groups)
            self.layer3 = self._make_layer(block, 64, n, stride=2, num_groups=num_groups)
            self.bn1 = nn.BatchNorm2d(64 * block.expansion)
            self.relu = nn.ReLU(inplace=True)
            self.avgpool = nn.AvgPool2d(8)
            self.fc = nn.Linear(64 * block.expansion, num_classes)

        elif dataset == 'imagenet':
            blocks = {18: BasicBlock, 34: BasicBlock, 50: Bottleneck, 101: Bottleneck, 152: Bottleneck, 200: Bottleneck}
            layers = {18: [2, 2, 2, 2], 34: [3, 4, 6, 3], 50: [3, 4, 6, 3], 101: [3, 4, 23, 3], 152: [3, 8, 36, 3],
                      200: [3, 24, 36, 3]}
            assert layers[depth], 'invalid detph for Pre-ResNet (depth should be one of 18, 34, 50, 101, 152, and 200)'

            self.inplanes = 64
            self.conv1 = nn.Conv2d(3, self.inplanes, kernel_size=7, stride=2, padding=3, bias=False)
            self.bn1 = nn.BatchNorm2d(64)
            self.relu = nn.ReLU(inplace=True)
            self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
            self.layer1 = self._make_layer(blocks[depth], 64, layers[depth][0], preact='no_preact')
            self.layer2 = self._make_layer(blocks[depth], 128, layers[depth][1], stride=2)
            self.layer3 = self._make_layer(blocks[depth], 256, layers[depth][2], stride=2)
            self.layer4 = self._make_layer(blocks[depth], 512, layers[depth][3], stride=2)
            self.bn2 = nn.BatchNorm2d(512 * blocks[depth].expansion)
            self.avgpool = nn.AvgPool2d(7, stride=1)
            self.fc = nn.Linear(512 * blocks[depth].expansion, num_classes)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

    def _make_layer(self, block, planes, blocks, num_groups=2, stride=1, preact='preact'):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * block.expansion),
            )

        layers = []
        layers.append(block(self.inplanes, planes, num_groups, stride, downsample, preact))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes, num_groups=num_groups))

        return nn.Sequential(*layers)

    def forward(self, x, keep_rate):
        if self.dataset == 'cifar10' or self.dataset == 'cifar100':
            x = self.conv1(x)

            x = self.layer1((x, keep_rate))[0]
            x = self.layer2((x, keep_rate))[0]
            x = self.layer3((x, keep_rate))[0]

            x = self.bn1(x)
            x = self.relu(x)
            x = self.avgpool(x)
            x = x.view(x.size(0), -1)
            # 2nd place, scale by 1./keep_rate
            # channel_num = round(x.size(1)*keep_rate)
            # if channel_num < x.size(1):
            #     x[:, channel_num:] = 0.
            #     x *= float(x.size(1))/channel_num
            x = self.fc(x)

        # need revision here
        elif self.dataset == 'imagenet':
            x = self.conv1(x)
            x = self.bn1(x)
            x = self.relu(x)
            x = self.maxpool(x)

            x = self.layer1(x)
            x = self.layer2(x)
            x = self.layer3(x)
            x = self.layer4(x)

            x = self.bn2(x)
            x = self.relu(x)
            x = self.avgpool(x)
            x = x.view(x.size(0), -1)
            x = self.fc(x)

        return x

