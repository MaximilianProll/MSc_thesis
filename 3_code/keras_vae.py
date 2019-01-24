from my_classes import DataGenerator, TensorBoardWrapper
from my_functions import get_available_gpus, split_dataframe, sampling, plot_latent_space

import datetime
import argparse
import sys
import os
import pandas as pd

from keras.layers import Dense, Input
from keras.layers import Conv2D, Flatten, Lambda
from keras.layers import Reshape, Conv2DTranspose, BatchNormalization
from keras import backend as K
from keras.models import Model
from keras.utils import plot_model
from keras.losses import mse, binary_crossentropy
from keras import optimizers
from keras.callbacks import ModelCheckpoint
from keras.models import load_model


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-w", "--weights", help="Load trained weights (.h5 file) saved by model.save_weights(filepath)")
    parser.add_argument("-m", "--model", help="Load a compiled model (.hdf5 file) saved by model.save(filepath)")
    parser.add_argument("--mse", action='store_true', help="Use mse loss instead of binary cross entropy (default)")

    parser.add_argument("-p", "--project_path", help="Specify project path, where the project is located.")
    parser.add_argument("-d", "--data_path", help="Specify path, where the data is located. E.g. /tmp/$SLURM_JOB_ID/05_images_masked/ ")

    req_grp = parser.add_argument_group(title='required arguments')
    req_grp.add_argument("-c", "--computer", help="Specify computer: use \'triton\', \'mac\' or \'workstation\'.",
                         required=True)
    args = parser.parse_args()

    if not args.project_path:
        if args.computer == 'triton':
            args.project_path = '/scratch/cs/ai_croppro'
        elif args.computer == 'mac':
            args.project_path = '/Users/maximilianproll/Dropbox (Aalto)/'
        elif args.computer == 'workstation':
            args.project_path = '/m/cs/scratch/ai_croppro'
        else:
            sys.exit('Please specify the computer this programme runs on using \'triton\', \'mac\' or \'workstation\'')

    if args.model and not args.project_path in args.model:

        if '..' in args.model:
            # remove leading '..'
            args.model = '/'.join(args.model.split('/')[1:])

        args.model = os.path.join(args.project_path, args.model)
        
    if args.weights and not args.project_path in args.weights:

        if '..' in args.weights:
            # remove leading '..'
            args.weights = '/'.join(args.weights.split('/')[1:])

        args.weights = os.path.join(args.project_path, args.weights)

    print(f'print available GPUs: \n {get_available_gpus()}')

    # Parameters
    params = {
        'path_to_csv': os.path.join(args.project_path, '2_data/01_MAVI_unzipped_preprocessed/MAVI2/2015/preprocessed_masked.csv'),
        'train_p': 0.8,
        'val_p': 0.1,
        'path_to_data': args.data_path if args.data_path else os.path.join(args.project_path, '2_data/05_images_masked/'),
        'has_cb_and_ext': True,
        'colour_band': 'BANDS-S2-L1C',
        'file_extension': '.tiff',
        'dim': (512, 512),
        'batch_size': 64,
        'n_channels': 13,
        'shuffle': True,
        'n_Conv': 6,
        'kernel_size': 3,
        'filters': 20,
        'latent_dim': 2,
        'epochs': 100
    }

    df = pd.read_csv(params['path_to_csv'])

    # split data frame into train, validation and test
    train_df, val_df, test_df = split_dataframe(df, params['train_p'], params['val_p'], )
    del df

    # create dictionaries of IDs and labels
    partition = {'train': train_df.index.tolist(), 'validation': val_df.index.tolist(), 'test': test_df.index.tolist()}

    labels = {**train_df['full crop loss scaled'].to_dict(), **val_df['full crop loss scaled'].to_dict(),
              **test_df['full crop loss scaled'].to_dict()}

    # Generators
    print('create DataGenerators')
    training_generator = DataGenerator(list_IDs=partition['train'],
                                       labels=labels,
                                       path_to_data=params['path_to_data'],
                                       has_cb_and_ext=params['has_cb_and_ext'],
                                       batch_size=params['batch_size'],
                                       dim=params['dim'],
                                       n_channels=params['n_channels'],
                                       shuffle=params['shuffle'])

    validation_generator = DataGenerator(list_IDs=partition['validation'],
                                         labels=labels,
                                         path_to_data=params['path_to_data'],
                                         has_cb_and_ext=params['has_cb_and_ext'],
                                         batch_size=params['batch_size'],
                                         dim=params['dim'],
                                         n_channels=params['n_channels'],
                                         shuffle=params['shuffle'])

    test_generator = DataGenerator(list_IDs=partition['test'],
                                   labels=labels,
                                   path_to_data=params['path_to_data'],
                                   has_cb_and_ext=params['has_cb_and_ext'],
                                   batch_size=params['batch_size'],
                                   dim=params['dim'],
                                   n_channels=params['n_channels'],
                                   shuffle=params['shuffle'])

    # network parameters
    input_shape = (params['dim'][0], params['dim'][1], params['n_channels'])
    kernel_size = params['kernel_size']
    filters = params['filters']
    latent_dim = params['latent_dim']
    epochs = params['epochs']

    print('create graph / model')
    # VAE model = encoder + decoder
    # build encoder model
    inputs = Input(shape=input_shape, name='encoder_input')
    x = inputs
    for i in range(params['n_Conv']):
        # filters *= 2
        x = Conv2D(filters=filters,
                   kernel_size=kernel_size,
                   activation='relu',
                   strides=2,
                   padding='same')(x)
        # x = BatchNormalization()(x)

    # shape info needed to build decoder model
    shape = K.int_shape(x)

    # generate latent vector Q(z|X)
    x = Flatten()(x)
    x = Dense(16, activation='relu')(x)
    z_mean = Dense(latent_dim, name='z_mean')(x)
    z_log_var = Dense(latent_dim, name='z_log_var')(x)

    # use reparameterization trick to push the sampling out as input
    # note that "output_shape" isn't necessary with the TensorFlow backend
    z = Lambda(sampling, output_shape=(latent_dim,), name='z')([z_mean, z_log_var])

    # instantiate encoder model
    encoder = Model(inputs, [z_mean, z_log_var, z], name='encoder')
    encoder.summary()
    plot_model(encoder, to_file=os.path.join(args.project_path, '4_runs/plots/vae_encoder.png'), show_shapes=True)

    # build decoder model
    latent_inputs = Input(shape=(latent_dim,), name='z_sampling')
    x = Dense(shape[1] * shape[2] * shape[3], activation='relu')(latent_inputs)
    x = Reshape((shape[1], shape[2], shape[3]))(x)

    for i in range(params['n_Conv']):
        # filters //= 2
        x = Conv2DTranspose(filters=filters,
                            kernel_size=kernel_size,
                            activation='relu',
                            strides=2,
                            padding='same')(x)
        # x = BatchNormalization()(x)

    outputs = Conv2DTranspose(filters=params['n_channels'],
                              kernel_size=kernel_size,
                              activation='sigmoid',
                              padding='same',
                              name='decoder_output')(x)

    # instantiate decoder model
    decoder = Model(latent_inputs, outputs, name='decoder')
    decoder.summary()
    plot_model(decoder, to_file=os.path.join(args.project_path, '4_runs/plots/vae_decoder.png'), show_shapes=True)

    # instantiate VAE model
    outputs = decoder(encoder(inputs)[2])
    vae = Model(inputs, outputs, name='vae')

    def my_vae_loss(_inputs, _outputs):
        # VAE loss = mse_loss or xent_loss + kl_loss
        if args.mse:
            reconstruction_loss = mse(K.flatten(_inputs), K.flatten(_outputs))
        else:
            reconstruction_loss = binary_crossentropy(K.flatten(_inputs),
                                                      K.flatten(_outputs))

        reconstruction_loss *= params['dim'][0] * params['dim'][1]
        kl_loss = 1 + z_log_var - K.square(z_mean) - K.exp(z_log_var)
        kl_loss = K.sum(kl_loss, axis=-1)
        kl_loss *= -0.5
        vae_loss = K.mean(reconstruction_loss + kl_loss)
        return vae_loss

    rmsprop = optimizers.RMSprop(lr=0.00001)
    vae.compile(optimizer=rmsprop, loss=my_vae_loss, metrics=['accuracy'])
    vae.summary()
    plot_model(vae, to_file=os.path.join(args.project_path, '4_runs/plots/vae.png'), show_shapes=True)

    # folder extension for bookkeeping
    datetime_string = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    config_string = str(params['n_Conv']) + 'n_Conv_' + datetime_string

    # add Keras callbacks for logging and for saving model checkpoints
    tbCallBack = TensorBoardWrapper(
        batch_gen=validation_generator,
        nb_steps=validation_generator.step_size,
        b_size=validation_generator.batch_size,
        log_dir=os.path.join(args.project_path, '4_runs/logging/TBlogs/' + config_string),
        histogram_freq=10,
        batch_size=validation_generator.batch_size,
        write_graph=True,
        write_grads=False,
        write_images=False,
        embeddings_freq=0,
        embeddings_layer_names=None,
        embeddings_metadata=None,
        embeddings_data=None,
        # update_freq='epoch',
    )

    model_checkpoint = ModelCheckpoint(
        filepath=os.path.join(args.project_path, '4_runs/logging/checkpoints/' + config_string + '_{epoch:04d}-{val_loss:.2f}.hdf5'),
        verbose=1,
        save_best_only=True,
        mode='min',
        period=1,
    )

    callbacks_list = [model_checkpoint, tbCallBack]

    if args.weights:
        print(f'loading weights from: {args.weights}')
        vae = vae.load_weights(args.weights)

    elif args.model:
        print(f'loading model from: {args.model}')
        vae = load_model(args.model, custom_objects={'my_vae_loss': my_vae_loss})

    else:
        # train the autoencoder
        print('start the training')
        vae.fit_generator(
            generator=training_generator,
            steps_per_epoch=training_generator.step_size,
            validation_data=validation_generator,
            validation_steps=validation_generator.step_size,
            epochs=epochs,
            use_multiprocessing=True,
            workers=os.cpu_count(),
            callbacks=callbacks_list
        )
        vae.save_weights(os.path.join(args.project_path, '4_runs/logging/weights/vae_' + config_string + '.h5'))
        print('training done')

    # define example images and their information tag for plotting them in the latent space
    example_images = [
        os.path.join(args.project_path, '2_data/05_images_masked/dataset1/0040491234-A_BANDS-S2-L1C.tiff'),
        os.path.join(args.project_path, '2_data/05_images_masked/dataset4/0090440170-A_BANDS-S2-L1C.tiff'),
        os.path.join(args.project_path, '2_data/05_images_masked/dataset1/0040506590-A_BANDS-S2-L1C.tiff'),
        os.path.join(args.project_path, '2_data/05_images_masked/dataset1/9810286471-A_BANDS-S2-L1C.tiff')
    ]

    ex_im_informations = [
        'only full crop loss',
        'both partial and full crop loss'
        'no loss',
        'only partial crop loss',
    ]
    plot_latent_space((encoder, decoder),
                      data_generator=test_generator,
                      example_images=example_images,
                      ex_im_informations=ex_im_informations,
                      path=os.path.join(args.project_path, '4_runs/plots/latent/')
                      )
