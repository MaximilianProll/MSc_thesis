import datetime
from my_classes import DataGenerator, TensorBoardWrapper
from my_functions import preprocess_df, split_dataframe, sampling
import argparse

from keras.layers import Dense, Input
from keras.layers import Conv2D, Flatten, Lambda
from keras.layers import Reshape, Conv2DTranspose, BatchNormalization
from keras import backend as K
from keras.models import Model
from keras.utils import plot_model
from keras.losses import mse, binary_crossentropy
from keras import optimizers
from keras.callbacks import ModelCheckpoint


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-w", "--weights", help="Load h5 model trained weights")
    parser.add_argument("-m", "--mse", action='store_true',
                        help="Use mse loss instead of binary cross entropy (default)")
    args = parser.parse_args()

    # Parameters
    params = {
        'path_to_csv': 'MAVI2/2015/rap_2015.csv',
        'train_p': 0.8,
        'val_p': 0.1,
        'path_to_data': 'data/',
        'colour_band': 'RAW',
        'file_extension': '.tiff',
        'dim': (512, 512),
        'batch_size': 32,
        'n_channels': 13,
        'shuffle': True,
        'n_Conv': 6,
        'kernel_size': 3,
        'filters': 20,
        'latent_dim': 2,
        'epochs': 1000
    }

    df = preprocess_df(params['path_to_csv'], params['path_to_data'], params['colour_band'], params['file_extension'])

    # add color spectrum and file extension to field parcel column in order to match to the file name
    # df['field parcel'] = df['field parcel'] + '_' + color_spectrum

    # split data frame into train, validation and test
    train_df, val_df, test_df = split_dataframe(df, params['train_p'], params['val_p'], )
    del df

    # create dictionaries of IDs and labels
    partition = {
        'train': train_df.index.tolist(), 'validation': val_df.index.tolist(), 'test': test_df.index.tolist()
    }
    labels = {**train_df['full crop loss scaled'].to_dict(), **val_df['full crop loss scaled'].to_dict(),
              **test_df['full crop loss scaled'].to_dict()}

    # Generators
    print('create DataGenerators')
    training_generator = DataGenerator(partition['train'], labels, params['path_to_data'], params['colour_band'],
                                       params['file_extension'], params['batch_size'], params['dim'],
                                       params['n_channels'], params['shuffle'])

    validation_generator = DataGenerator(partition['validation'], labels, params['path_to_data'], params['colour_band'],
                                         params['file_extension'], params['batch_size'], params['dim'],
                                         params['n_channels'], params['shuffle'])

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
    plot_model(encoder, to_file='plots/vae_cnn_encoder.png', show_shapes=True)

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
    plot_model(decoder, to_file='plots/vae_cnn_decoder.png', show_shapes=True)

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
    plot_model(vae, to_file='plots/vae_cnn.png', show_shapes=True)

    # folder extension for bookkeeping
    datetime_string = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    config_string = str(params['n_Conv']) + 'n_Conv_' + datetime_string

    # add Keras callbacks for logging and for saving model checkpoints
    tbCallBack = TensorBoardWrapper(
        validation_generator, val_df.shape[0] // validation_generator.batch_size, validation_generator.batch_size,
        log_dir='logging/TBlogs/' + config_string, histogram_freq=10, batch_size=validation_generator.batch_size,
        write_graph=True, write_grads=False, write_images=False, embeddings_freq=0,
        embeddings_layer_names=None, embeddings_metadata=None,
        embeddings_data=None, update_freq='epoch')

    model_checkpoint = ModelCheckpoint(filepath='logging/checkpoints/' + config_string + '.hdf5', verbose=1,
                                       save_best_only=True, mode='min', period=1)

    callbacks_list = [model_checkpoint, tbCallBack]

    if args.weights:
        vae = vae.load_weights(args.weights)
    else:
        # train the autoencoder
        vae.fit_generator(
            generator=training_generator,
            validation_data=validation_generator,
            epochs=epochs,
            use_multiprocessing=True,
            workers=6,
            callbacks=callbacks_list
        )
        vae.save_weights('logging/weights/vae_' + config_string + '.h5')
        print('training done')