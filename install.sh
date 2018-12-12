#!/usr/bin/env bash

conda create -n edward python=3.6 pillow pandas matplotlib tqdm jupyterlab pydot scikit-image -y

conda activate edward

#conda install -c conda-forge tensorflow keras
conda install -c conda-forge tensorflow-gpu keras-gpu cudatoolkit=9.0 -y

# pip install --upgrade tensorflow-probability
# pip install --upgrade tensorflow-probability-gpu

pip install edward sentinelhub
