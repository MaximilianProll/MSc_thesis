import argparse
import datetime
import os
import sys

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.model_selection import train_test_split
from sklearn.utils import class_weight

from my_functions import get_OS, plot_confusion_matrix, f1, my_acc, f1_macro

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
    req_grp.add_argument("-m", "--model", required=True,
                         help="Load trained and compiled models (.hdf5 file) saved by model.save(filepath). "
                              "Path until parent directory: e.g \'4_runs/logging/models/")
    parser.add_argument("-p", "--project_path", help="Specify project path, where the project is located.")
    parser.add_argument("-d", "--data_path",
                        help="Specify path, where the data is located. E.g. /tmp/$SLURM_JOB_ID/05_images_masked/ ")
    parser.add_argument('-e', "--epochs", type=int, help="Specify the number of training epochs")
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

    # Parameters
    path_to_data = args.data_path if args.data_path else os.path.join(args.project_path, '2_data/04_toydata_64x64/')
    im_dim = (64, 64)
    n_channels = 1
    input_shape = (im_dim[0], im_dim[1], n_channels)
    epochs = args.epochs if args.epochs else 200
    batch_normalization = args.batch_normalization
    use_bias = not batch_normalization  # if batch_normalization is used, a bias term can be omitted
    batch_size = 16

    # load np arrays
    X = np.load(os.path.join(path_to_data, 'X64_top5.npy'))
    y = np.load(os.path.join(path_to_data, 'Y64_top5.npy'))

    index_full_cl = 0
    index_partial_cl = 1
    index_loss_cat_4d = 2
    index_loss_cat_2d = 3
    index_plant_cat = 4

    full_cl = np.reshape(y[:, index_full_cl], (len(y), 1))
    partial_cl = np.reshape(y[:, index_partial_cl], (len(y), 1))

    # convert categorical data to one hot encoding
    df = pd.DataFrame(y[:, index_loss_cat_4d])
    df[0] = df[0].astype(int).astype('category')
    loss_cat_4d_one_hot = pd.get_dummies(df[0]).values

    df = pd.DataFrame(y[:, index_loss_cat_2d])
    df[0] = df[0].astype(int).astype('category')
    loss_cat_2d_one_hot = pd.get_dummies(df[0]).values

    df = pd.DataFrame(y[:, index_plant_cat])
    df[0] = df[0].astype(int).astype('category')
    plant_cat_one_hot = pd.get_dummies(df[0]).values

    n_loss_cat_4d = loss_cat_4d_one_hot.shape[-1]
    n_loss_cat_2d = loss_cat_2d_one_hot.shape[-1]
    n_plant_cat = plant_cat_one_hot.shape[-1]

    index_loss_cat_4d_one_hot = np.arange(index_loss_cat_4d, index_loss_cat_4d + n_loss_cat_4d)
    index_loss_cat_2d_one_hot = np.arange(max(index_loss_cat_4d_one_hot) + 1, max(index_loss_cat_4d_one_hot) + 1 + n_loss_cat_2d)
    index_plant_cat_one_hot = np.arange(max(index_loss_cat_2d_one_hot) + 1, max(index_loss_cat_2d_one_hot) + 1 + n_plant_cat)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        np.concatenate((full_cl, partial_cl, loss_cat_4d_one_hot, loss_cat_2d_one_hot, plant_cat_one_hot), 1),
        test_size=0.20, random_state=42)
    X_val, X_test, y_val, y_test = train_test_split(X_test, y_test, test_size=0.50, random_state=42)

    # save some RAM
    del X, y, df, loss_cat_4d_one_hot, loss_cat_2d_one_hot, plant_cat_one_hot, full_cl, partial_cl

    print(f'load trained encoder from {args.model}')
    encoder = tf.keras.models.load_model(os.path.join(args.model, 'encoder.hdf5'))
    encoder.trainable = False
    latent_dim = encoder.output[0].shape.dims[1].value

    # folder extension for bookkeeping
    datetime_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    hparam_str = 'prediction_64x64_'
    hparam_str += args.param_alternation + '_' if args.param_alternation else ''
    hparam_str += str(latent_dim) + 'z_'
    hparam_str += str(int(batch_normalization)) + 'BN_'
    hparam_str += str(epochs) + 'ep_'
    hparam_str += datetime_str

    os.makedirs(os.path.join(args.project_path, '4_runs/plots/', hparam_str), exist_ok=True)

    # build the computational graph
    encoder_input = tf.keras.layers.Input(shape=input_shape, name='encoder_input')
    z = encoder(encoder_input)[2]

    # build prediction models
    out_full_cl = tf.keras.layers.Dense(1, use_bias=use_bias)(z)
    out_partial_cl = tf.keras.layers.Dense(1, use_bias=use_bias)(z)
    out_loss_cat_4d_prob = tf.keras.layers.Dense(n_loss_cat_4d, use_bias=use_bias)(z)
    out_loss_cat_2d_prob = tf.keras.layers.Dense(n_loss_cat_2d, use_bias=use_bias)(z)
    out_plant_cat_prob = tf.keras.layers.Dense(n_plant_cat, use_bias=use_bias)(z)

    if batch_normalization:
        out_full_cl = tf.keras.layers.BatchNormalization()(out_full_cl)
        out_partial_cl = tf.keras.layers.BatchNormalization()(out_partial_cl)
        out_loss_cat_4d_prob = tf.keras.layers.BatchNormalization()(out_loss_cat_4d_prob)
        out_loss_cat_2d_prob = tf.keras.layers.BatchNormalization()(out_loss_cat_2d_prob)
        out_plant_cat_prob = tf.keras.layers.BatchNormalization()(out_plant_cat_prob)

    out_full_cl = tf.keras.layers.Activation(activation='sigmoid', name='out_full_cl')(out_full_cl)
    out_partial_cl = tf.keras.layers.Activation(activation='sigmoid', name='out_partial_cl')(out_partial_cl)
    out_loss_cat_4d_prob = tf.keras.layers.Activation(activation='softmax', name='out_loss_cat_4d_prob')(out_loss_cat_4d_prob)
    out_loss_cat_2d_prob = tf.keras.layers.Activation(activation='softmax', name='out_loss_cat_2d_prob')(out_loss_cat_2d_prob)
    out_plant_cat_prob = tf.keras.layers.Activation(activation='softmax', name='out_plant_cat_prob')(out_plant_cat_prob)

    # instantiate prediction model
    pred_model = tf.keras.models.Model(
        inputs=encoder_input,
        outputs=[out_full_cl, out_partial_cl, out_loss_cat_4d_prob, out_loss_cat_2d_prob, out_plant_cat_prob],
        name='pred_model')
    rmsprop = tf.keras.optimizers.RMSprop(lr=0.0001)

    pred_model.compile(optimizer=rmsprop,
                       loss=['mse', 'mse', 'binary_crossentropy', 'binary_crossentropy', 'binary_crossentropy'],
                       metrics={'out_loss_cat_2d_prob': [f1, my_acc],
                                'out_loss_cat_4d_prob': [f1_macro, my_acc],
                                'out_plant_cat_prob': [f1_macro, my_acc]})
    pred_model.summary()
    tf.keras.utils.plot_model(
        pred_model, to_file=os.path.join(args.project_path, '4_runs/plots/', hparam_str, 'pred_model.png'),
        show_shapes=True)

    # add callbacks for:
    # - TensorBoard logger
    # - logging and for saving model checkpoints

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
        filepath=os.path.join(args.project_path, '4_runs/logging/checkpoints/pred_model_' + hparam_str + '.hdf5'),
        verbose=1,
        save_best_only=True,
        mode='min',
        period=1,
    )
    callbacks_list = [
        model_checkpoint,
        tbCallBack
    ]

    print('start the training')
    pred_model.fit(
        x=X_train, y=[y_train[:, index_full_cl], y_train[:, index_partial_cl], y_train[:, index_loss_cat_4d_one_hot], y_train[:, index_loss_cat_2d_one_hot], y_train[:, index_plant_cat_one_hot]],
        batch_size=batch_size,
        validation_data=(X_val, [y_val[:, index_full_cl], y_val[:, index_partial_cl], y_val[:, index_loss_cat_4d_one_hot], y_val[:, index_loss_cat_2d_one_hot], y_val[:, index_plant_cat_one_hot]]),
        epochs=epochs if not args.debug else 1,
        callbacks=callbacks_list,
        workers=os.cpu_count(),
        use_multiprocessing=True,
    )
    print('training done')

    # save models and weights
    dir_models = os.path.join(args.project_path, '4_runs/logging/models/', hparam_str)
    os.makedirs(dir_models, exist_ok=True)
    pred_model.save(os.path.join(dir_models, 'pred_model.hdf5'))

    dir_weights = os.path.join(args.project_path, '4_runs/logging/weights/', hparam_str)
    os.makedirs(dir_weights, exist_ok=True)
    pred_model.save_weights(os.path.join(dir_weights, 'pred_model.h5'))
    print('models and weights saved')

    print('evaluate the model')
    scores = pred_model.evaluate(
        x=X_test, y=[y_test[:, index_full_cl], y_test[:, index_partial_cl], y_test[:, index_loss_cat_4d_one_hot], y_test[:, index_loss_cat_2d_one_hot], y_test[:, index_plant_cat_one_hot]],
        batch_size=batch_size,
        workers=os.cpu_count(),
        use_multiprocessing=True,
    )

    for score, metric in zip(np.round(scores, 3), pred_model.metrics_names):
        print(f'{metric}: {score}')

    print('prediction')
    y_pred_full_cl, y_pred_partial_cl, y_pred_loss_cat_4d_prob, y_pred_loss_cat_2d_prob, y_pred_plant_cat_prob = pred_model.predict(
        x=X_test,
        batch_size=batch_size,
        workers=os.cpu_count(),
        use_multiprocessing=True,
    )

    plot_confusion_matrix(
        np.argmax(y_test[:, index_loss_cat_4d_one_hot], axis=1),
        np.argmax(y_pred_loss_cat_4d_prob, axis=1),
        class_names=['full loss', 'partial loss', 'full and partial loss', 'no loss'],
        path=os.path.join(args.project_path, '4_runs/plots/', hparam_str),
        file_name_prefix='loss_cat_4d_',
        normalize=False,
        title=f'Loss category 4D {args.param_alternation}'
    )

    plot_confusion_matrix(
        np.argmax(y_test[:, index_loss_cat_2d_one_hot], axis=1),
        np.argmax(y_pred_loss_cat_2d_prob, axis=1),
        class_names=['no loss', 'some loss'],
        path=os.path.join(args.project_path, '4_runs/plots/', hparam_str),
        file_name_prefix='loss_cat_2d_',
        normalize=False,
        title=f'Loss category 2D {args.param_alternation}'
    )

    # top_5_plants = ['Rehuohra', 'Kaura', 'Mallasohra', 'Kevätvehnä', 'Kevätrypsi']
    top_5_plants = ['Feed Barley', 'Oats', 'Malting Barley', 'Spring Wheat', 'Spring Rapeseed']

    plot_confusion_matrix(
        np.argmax(y_test[:, index_plant_cat_one_hot], axis=1),
        np.argmax(y_pred_plant_cat_prob, axis=1),
        class_names=top_5_plants,
        path=os.path.join(args.project_path, '4_runs/plots/', hparam_str),
        file_name_prefix='plant_cat_',
        normalize=False,
        title=f'Plant category {args.param_alternation}'
    )

    print()
