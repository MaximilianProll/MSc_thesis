#!/bin/bash -l

# request resources
# -----------------------
#SBATCH --time=0-05:00:00
#SBATCH --mem-per-cpu 10G
#SBATCH --cpus-per-task=20
#SBATCH --gres=gpu:1
#SBATCH --constraint='pascal|volta'
#SBATCH --array=1-10

# set -x # print all output to log file

# load environment
module purge
module load anaconda3
source activate edward

which python
# env

# copy tfrecords files
cd /scratch/cs/ai_croppro/
mkdir /tmp/$SLURM_JOB_ID                                    # get a directory where you will send all output from your program
cp 2_data/05_images_masked/*.tfrecord /tmp/$SLURM_JOB_ID    # copy tfrecords files to temporary directory
cp 2_data/05_images_masked/*.txt /tmp/$SLURM_JOB_ID         # copy other necessary files to temporary directory
                                                            # run python script with temporary directory as input for the images

# define the dimensionality of latent space and pass it as argument to python script
z=$((2**$SLURM_ARRAY_TASK_ID))
echo "latent dim: $z"

srun python 3_code/tf_vae_tfrecords.py -c triton --data_path /tmp/$SLURM_JOB_ID/ -z $z
