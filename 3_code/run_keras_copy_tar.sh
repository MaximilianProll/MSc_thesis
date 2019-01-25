#!/bin/bash -l

# request resources
# -----------------------
#SBATCH --time=0-12:00:00
#SBATCH --mem-per-cpu 32G
#SBATCH --cpus-per-task=6

# TODO: set num of cpu properly

#SBATCH --gres=gpu:1
#SBATCH --constraint='kepler|pascal|volta'

# set -x # print all output to log file

# load environment
module purge
module load anaconda3
source activate edward

which python
# env

# copy tar files
cd /scratch/cs/ai_croppro/
mkdir /tmp/$SLURM_JOB_ID                                # get a directory where you will send all output from your program
cp 2_data/05_images_masked.tar.gz /tmp/$SLURM_JOB_ID    # copy zipped images to temporary directory
cd /tmp/$SLURM_JOB_ID                                   # go to new temporary directory and
tar xzf 05_images_masked.tar.gz                         # unzip images in temporary directory

cd /scratch/cs/ai_croppro/                              # go back to project folder and run python script with
                                                        # temporary directory as input for the images
python 3_code/keras_vae.py -c triton --data_path /tmp/$SLURM_JOB_ID/05_images_masked/

#TODO: copy tfrecords files
#cp data.tfrecord /tmp/$SLURM_JOB_ID
#python 3_code/keras_vae.py -c triton --data_path /tmp/$SLURM_JOB_ID/05_images_masked/