import argparse
import datetime
import os
import sys

import tensorflow as tf

from my_classes import MyCallbackDecoder, MyCallbackCompOrigDecoded
from my_functions import get_available_gpus, sampling, create_tfdataDataset, get_OS

op_sys = get_OS()
if op_sys == 'Darwin':
    # fix for macOS issue regarding library import error:
    # OMP: Error #15: Initializing libiomp5.dylib, but found libiomp5.dylib already initialized.
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    req_grp = parser.add_argument_group(title='required arguments')
    req_grp.add_argument("-c", "--computer", help="Specify computer: use \'triton\', \'mac\' or \'workstation\'.",
                         required=True)
    parser.add_argument("-p", "--project_path", help="Specify project path, where the project is located.")
    parser.add_argument("-d", "--data_path",
                        help="Specify path, where the data is located. E.g. /tmp/$SLURM_JOB_ID/05_images_masked/ ")
    parser.add_argument("-m", "--model", help="Load compiled models (.hdf5 file) saved by model.save(filepath). Path "
                                              "until parent directory: e.g \'4_runs/logging/models/")
    parser.add_argument("-w", "--weights", help="Load trained weights (.h5 file) saved by model.save_weights(filepath)."
                                                "Path until parent directory: e.g \'4_runs/logging/weights/")
    parser.add_argument("--mse", action='store_true', help="Use mse loss instead of binary cross entropy (default)")
    parser.add_argument("--in_field_loss", action='store_true', help="Only compute the loss inside the field")
    parser.add_argument('-e', "--epochs", type=int, help="Specify the number of training epochs")
    parser.add_argument('-z', "--latent_dim", type=int, help="Specify the dimensionality of latent space")
    parser.add_argument("--n_conv", type=int, help="Specify the number of convolutional layers.")
    parser.add_argument("--batch_normalization", action='store_true', default=False,
                        help="Specify if batch normalizations shall be applied. Default False.")
    parser.add_argument("--param_alternation", type=str,
                        help="When looping over certain hyper parameters, this flag adds the hyper parameter of "
                             "interest to the fron of the hyper parameter string.")
    parser.add_argument("--debug", action='store_true', help="Run in debug mode - reduces epochs and steps_per_epoch")
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

    print('available GPUs:')
    get_available_gpus()
    # gpu_device_ID = get_device_id(gpu_pci_bus_id)

    # Parameters
    path_to_csv = os.path.join(
        args.project_path, '2_data/01_MAVI_unzipped_preprocessed/2015/preprocessed_masked.csv')
    path_to_data = args.data_path if args.data_path else os.path.join(args.project_path, '2_data/03_images_subset_masked/')
    im_dim = (512, 512)
    n_channels = 13
    input_shape = (im_dim[0], im_dim[1], n_channels)
    n_Conv = args.n_conv if args.n_conv else 3
    kernel_size = 3
    filters = 20
    latent_dim = args.latent_dim if args.latent_dim else 1024
    epochs = args.epochs if args.epochs else 100
    batch_normalization = args.batch_normalization
    loss_fct = 'MSE' if args.mse else 'X-Ent'
    n_parallel_readers = 4
    use_bias = not batch_normalization  # if batch_normalization is used, a bias term can be omitted

    if not op_sys == 'Darwin':
        batch_size = 64
    else:
        batch_size = 16

    # create Dataset objects
    ds_train, steps_per_epoch_train = create_tfdataDataset(path_to_data, 'train', False, batch_size, batch_size, n_parallel_readers)
    ds_val, steps_per_epoch_val = create_tfdataDataset(path_to_data, 'val', False, batch_size, batch_size, n_parallel_readers)
    ds_test, steps_per_epoch_test = create_tfdataDataset(path_to_data, 'test', False, batch_size, batch_size, n_parallel_readers)

    # folder extension for bookkeeping
    datetime_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    hparam_str = args.param_alternation + '_' if args.param_alternation else ''
    hparam_str += str(latent_dim) + 'z_'
    hparam_str += str(n_Conv) + 'Conv_'
    hparam_str += str(int(batch_normalization)) + 'BN_'
    hparam_str += str(epochs) + 'ep_'
    hparam_str += loss_fct + '_'
    hparam_str += str(int(args.in_field_loss)) + 'IFL_'
    hparam_str += datetime_str

    os.makedirs(os.path.join(args.project_path, '4_runs/plots/', hparam_str), exist_ok=True)

    print('create graph / model')
    # VAE model = encoder + decoder
    # build encoder model
    inputs = tf.keras.layers.Input(shape=input_shape, name='encoder_input')
    x = inputs

    if batch_normalization:
        x = tf.keras.layers.BatchNormalization()(x)

    for i in range(n_Conv):
        x = tf.keras.layers.Conv2D(filters=filters if i < 5 else filters // 2,
                                   kernel_size=kernel_size,
                                   strides=2 if i < 5 else 1,
                                   padding='same',
                                   use_bias=use_bias)(x)

        if batch_normalization:
            x = tf.keras.layers.BatchNormalization()(x)

        x = tf.keras.layers.Activation(activation='relu')(x)

    # shape info needed to build decoder model
    shape = tf.keras.backend.int_shape(x)

    x = tf.keras.layers.Flatten()(x)

    # generate latent vector Q(z|X)
    z_mean = tf.keras.layers.Dense(latent_dim, use_bias=use_bias)(x)
    z_log_var = tf.keras.layers.Dense(latent_dim, use_bias=use_bias)(x)

    if batch_normalization:
        z_mean = tf.keras.layers.BatchNormalization()(z_mean)
        z_log_var = tf.keras.layers.BatchNormalization()(z_log_var)

    z_mean = tf.keras.layers.Activation(activation='relu', name='z_mean')(z_mean)
    z_log_var = tf.keras.layers.Activation(activation='relu', name='z_log_var')(z_log_var)

    # use reparameterization trick to push the sampling out as input
    # note that "output_shape" isn't necessary with the TensorFlow backend
    z = tf.keras.layers.Lambda(sampling, output_shape=(latent_dim,), name='z')([z_mean, z_log_var])

    # instantiate encoder model
    encoder = tf.keras.models.Model(inputs, [z_mean, z_log_var, z], name='encoder')
    encoder.summary()
    tf.keras.utils.plot_model(
        encoder, to_file=os.path.join(args.project_path, '4_runs/plots/', hparam_str, 'vae_encoder.png'),
        show_shapes=True)

    # build decoder model
    latent_inputs = tf.keras.layers.Input(shape=(latent_dim,), name='z_sampling')
    x = latent_inputs

    if batch_normalization:
        x = tf.keras.layers.BatchNormalization()(x)

    x = tf.keras.layers.Dense(shape[1] * shape[2] * shape[3], use_bias=use_bias)(x)

    if batch_normalization:
        x = tf.keras.layers.BatchNormalization()(x)

    x = tf.keras.layers.Activation(activation='relu')(x)

    x = tf.keras.layers.Reshape((shape[1], shape[2], shape[3]))(x)

    for i in reversed(range(n_Conv)):
        x = tf.keras.layers.Conv2DTranspose(filters=filters if i < 5 else filters // 2,
                                            kernel_size=kernel_size,
                                            strides=2 if i < 5 else 1,
                                            padding='same',
                                            use_bias=use_bias)(x)
        if batch_normalization:
            x = tf.keras.layers.BatchNormalization()(x)

        x = tf.keras.layers.Activation(activation='relu')(x)

    # after the last Conv2DTranspose bring the output in the origninal shape
    x = tf.keras.layers.Conv2DTranspose(filters=n_channels,
                                        kernel_size=kernel_size,
                                        padding='same',
                                        use_bias=use_bias)(x)

    if batch_normalization:
        x = tf.keras.layers.BatchNormalization()(x)

    outputs = tf.keras.layers.Activation(activation='relu', name='decoder_output')(x)

    # instantiate decoder model
    decoder = tf.keras.models.Model(latent_inputs, outputs, name='decoder')
    decoder.summary()
    tf.keras.utils.plot_model(
        decoder, to_file=os.path.join(args.project_path, '4_runs/plots/', hparam_str, 'vae_decoder.png'),
        show_shapes=True)

    # instantiate VAE model
    outputs = decoder(encoder(inputs)[2])
    vae = tf.keras.models.Model(inputs, outputs, name='vae')

    def KL_Div(y_true, y_pred):
        kl_div = 1 + z_log_var - tf.keras.backend.square(z_mean) - tf.keras.backend.exp(z_log_var)
        kl_div = tf.keras.backend.sum(kl_div, axis=-1)
        kl_div *= -0.5
        return kl_div

    def recon_loss(y_true, y_pred):

        if args.in_field_loss:
            # only keep these parts of the true image where the field actually is
            mask = tf.math.greater(y_true, 0)
            y_true = tf.boolean_mask(y_true, mask)
            y_pred = tf.boolean_mask(y_pred, mask)


        if args.mse:
            reconstruction_loss = tf.keras.losses.mse(
                tf.keras.backend.flatten(y_true), tf.keras.backend.flatten(y_pred))
        else:
            reconstruction_loss = tf.keras.losses.binary_crossentropy(
                tf.keras.backend.flatten(y_true), tf.keras.backend.flatten(y_pred))

        reconstruction_loss *= im_dim[0] * im_dim[1]
        return reconstruction_loss

    def vae_loss(y_true, y_pred):
        # VAE loss = mse_loss or xent_loss + kl_loss
        reconstruction_loss = recon_loss(y_true, y_pred)
        kl_div = KL_Div(y_true, y_pred)
        vae_loss = tf.keras.backend.mean(reconstruction_loss + kl_div)
        return vae_loss

    rmsprop = tf.keras.optimizers.RMSprop(lr=0.00001)
    vae.compile(optimizer=rmsprop, loss=vae_loss, metrics=[KL_Div, recon_loss])
    vae.summary()
    tf.keras.utils.plot_model(
        vae, to_file=os.path.join(args.project_path, '4_runs/plots/', hparam_str, 'vae.png'),
        show_shapes=True)

    if args.weights:
        print(f'loading weights from: {args.weights}')
        vae = vae.load_weights(os.path.join(args.weights, 'vae.h5'))
        encoder = encoder.load_weights(os.path.join(args.weights, 'encoder.h5'))
        decoder = decoder.load_weights(os.path.join(args.weights, 'decoder.h5'))

    elif args.model:
        print(f'loading models from: {args.model}')
        vae = tf.keras.models.load_model(os.path.join(args.model, 'vae.hdf5'),
                                         custom_objects={'vae_loss': vae_loss,
                                                         'KL_Div': KL_Div,
                                                         'recon_loss': recon_loss})
        encoder = tf.keras.models.load_model(os.path.join(args.model, 'encoder.hdf5'))
        decoder = tf.keras.models.load_model(os.path.join(args.model, 'decoder.hdf5'))
        print('models loaded')

    else:
        # train the autoencoder

        # add callbacks for:
        # - creating saving decoded image after log_freq epochs
        # - TensorBoard logger
        # - logging and for saving model checkpoints

        mycb_comparison = MyCallbackCompOrigDecoded(
            log_dir=os.path.join(args.project_path, '4_runs/plots/', hparam_str, 'comparison'),
            dataset=ds_test, num_examples=10, log_freq=5)

        mycb_decoder = MyCallbackDecoder(
            decoder, log_dir=os.path.join(args.project_path, '4_runs/plots/', hparam_str, 'decoder'),
            num_examples_to_generate=16, log_freq=5)

        tbCallBack = tf.keras.callbacks.TensorBoard(
            log_dir=os.path.join(args.project_path, '4_runs/logging/TBlogs/' + hparam_str),
            histogram_freq=0,  # TODO: fix error when setting histogram_freq > 0
            batch_size=batch_size,
            write_graph=True,
            write_grads=False,
            write_images=False,
            embeddings_freq=0,
            embeddings_layer_names=None,
            embeddings_metadata=None,
            embeddings_data=None,
        )

        model_checkpoint = tf.keras.callbacks.ModelCheckpoint(
            filepath=os.path.join(args.project_path, '4_runs/logging/checkpoints/vae_' + hparam_str + '.hdf5'),
            verbose=1,
            save_best_only=True,
            mode='min',
            period=1,
        )
        callbacks_list = [
            mycb_comparison,
            mycb_decoder,
            model_checkpoint,
            tbCallBack
        ]

        print('start the training')
        vae.fit(
            ds_train,
            steps_per_epoch=steps_per_epoch_train if not args.debug else 3,
            validation_data=ds_val,
            validation_steps=steps_per_epoch_val if not args.debug else 3,
            epochs=epochs if not args.debug else 3,
            callbacks=callbacks_list,
        )
        print('training done')

        # save models and weights
        dir_models = os.path.join(args.project_path, '4_runs/logging/models/', hparam_str)
        os.makedirs(dir_models, exist_ok=True)
        vae.save(os.path.join(dir_models, 'vae.hdf5'))
        encoder.save(os.path.join(dir_models, 'encoder.hdf5'))
        decoder.save(os.path.join(dir_models, 'decoder.hdf5'))

        dir_weights = os.path.join(args.project_path, '4_runs/logging/weights/', hparam_str)
        os.makedirs(dir_weights, exist_ok=True)
        vae.save_weights(os.path.join(dir_weights, 'vae.h5'))
        encoder.save_weights(os.path.join(dir_weights, 'encoder.h5'))
        decoder.save_weights(os.path.join(dir_weights, 'decoder.h5'))
        print('models and weights saved')

    if False:
        # define example images and their information tag for plotting them in the latent space
        example_images = [
            os.path.join(args.project_path, '2_data/05_images_masked/dataset1/0040491234-A_BANDS-S2-L1C.tiff'),
            os.path.join(args.project_path, '2_data/05_images_masked/dataset1/8930312979-A_BANDS-S2-L1C.tiff'),
            os.path.join(args.project_path, '2_data/05_images_masked/dataset1/0090248594-A_BANDS-S2-L1C.tiff'),
            os.path.join(args.project_path, '2_data/05_images_masked/dataset1/9810286471-A_BANDS-S2-L1C.tiff')
        ]

        if op_sys == 'Darwin':
            example_images = [
                os.path.join(args.project_path, '2_data/05_images_masked/dataset8/0050496277-A_BANDS-S2-L1C.tiff'),
                os.path.join(args.project_path, '2_data/05_images_masked/dataset8/0050496277-A_BANDS-S2-L1C.tiff'),
                os.path.join(args.project_path, '2_data/05_images_masked/dataset8/0050496277-A_BANDS-S2-L1C.tiff'),
                os.path.join(args.project_path, '2_data/05_images_masked/dataset8/0050496277-A_BANDS-S2-L1C.tiff')
            ]

        ex_im_informations = [
            'only full crop loss',
            'both partial and full crop loss',
            'no loss',
            'only partial crop loss',
        ]

        plot_latent_space((encoder, decoder),
                          dataset=ds_test,
                          steps_per_epoch=steps_per_epoch_test,
                          batch_size=batch_size,
                          example_images=example_images,
                          ex_im_informations=ex_im_informations,
                          path=os.path.join(args.project_path, '4_runs/plots/', hparam_str, 'latent')
                          )
