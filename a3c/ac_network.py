import tensorflow as tf
import numpy as np

# Clipping ratio for gradients
CLIP_NORM = 40.0

class AC_Network():
    def __init__(self, s_size, a_size, scope, trainer, hyper, summary_level=1):
        with tf.variable_scope(scope):
            # Input
            he_init = tf.contrib.layers.variance_scaling_initializer()
            self.training = training = tf.placeholder_with_default(False, shape=(), name='training')
            self.inputs = tf.placeholder(shape=[None, s_size], dtype=tf.float32, name='inputs')

            net = self.inputs if self.inputs.get_shape().ndims == 3 else tf.expand_dims(self.inputs, [1])
            net = tf.layers.dropout(net, rate=hyper.dropout, training=training, name='input_drop')

            # 1st dense layer
            if hyper.net[0]:
                with tf.name_scope('first_dense'):
                    net = tf.layers.dense(net, hyper.net[0], kernel_initializer=he_init, activation=tf.nn.elu, name='first_act')
                    net = tf.layers.dropout(net, rate=hyper.dropout, training=training, name='first_act_drop')
                    if summary_level >= 2: tf.summary.histogram('act', net)

            # Recurrent network for temporal dependencies
            # Original: https://medium.com/emergent-future/simple-reinforcement-learning-with-tensorflow-part-8-asynchronous-actor-critic-agents-a3c-c88f72a5e9f2
            # Multi-layer: https://medium.com/@erikhallstrm/using-the-tensorflow-multilayered-lstm-api-f6e7da7bbe40
            l_layers, l_units = len(hyper.net[1]), hyper.net[1][0]
            with tf.name_scope('lstm'):
                cell = [tf.nn.rnn_cell.LSTMCell(l_units) for _ in range(l_layers)]
                output_keep = tf.cond(self.training, lambda: 1 - hyper.dropout, lambda: 1.)
                cell = [tf.nn.rnn_cell.DropoutWrapper(c, output_keep_prob=output_keep) for c in cell]
                cell = tf.nn.rnn_cell.MultiRNNCell(cell)

                self.rnn_prev = tf.placeholder(dtype=tf.float32, shape=[l_layers, 2, None, l_units], name="rnn_state")
                l = tf.unstack(self.rnn_prev, axis=0)
                rnn_tuple_state = tuple([
                    tf.nn.rnn_cell.LSTMStateTuple(l[i][0], l[i][1])
                    for i in range(l_layers)
                ])

                output, self.rnn_next = tf.nn.dynamic_rnn(
                    cell, net,
                    initial_state=rnn_tuple_state,
                    time_major=False)
                # self.rnn_next = (lstm_c[:1, :], lstm_h[:1, :])
                rnn = tf.reshape(output, [-1, l_units])
                if summary_level >= 2: tf.summary.histogram('out', rnn)

            # Policy function
            with tf.name_scope('policy'):
                net = rnn
                for i, units in enumerate(hyper.net[2]):
                    net = tf.layers.dense(net, units, kernel_initializer=he_init, activation=tf.nn.elu, name=f'pol_act{i}')
                    net = tf.layers.dropout(net, rate=hyper.dropout, training=training, name=f'pol_act_drop{i}')
                    if summary_level >= 2: tf.summary.histogram('act', net)
                self.policy = tf.squeeze(tf.layers.dense(net, 1, kernel_initializer=he_init, name='pol_out'))

            # Value estimation
            with tf.name_scope('value'):
                net = rnn
                for i, units in enumerate(hyper.net[2]):
                    net = tf.layers.dense(net, units, kernel_initializer=he_init, activation=tf.nn.elu, name=f'val_act{i}')
                    net = tf.layers.dropout(net, rate=hyper.dropout, training=training, name=f'val_act_drop{i}')
                    if summary_level >= 2: tf.summary.histogram('act', net)
                self.value = tf.layers.dense(net, 1, kernel_initializer=he_init, name='val_out')

            # Only the worker network need ops for loss functions and gradient updating.
            if scope != 'global':
                update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS, scope)
                with tf.name_scope('losses'), tf.control_dependencies(update_ops):
                    """ https://goo.gl/ZU2Z9a
                    NOTE! These loss functions have been altered dramatically, and may not be correct. See original
                    implementation at https://github.com/awjuliani/DeepRL-Agents/blob/master/A3C-Doom.ipynb:
                    
                    Value Loss: L = Σ(R - V(s))²
                    Policy Loss: L = -log(π(s)) * A(s) - β*H(π)
                    """
                    self.actions = tf.placeholder(shape=[None], dtype=tf.float32, name='actions')
                    self.target_v = tf.placeholder(shape=[None], dtype=tf.float32, name='target_v')
                    self.advantages = tf.placeholder(shape=[None], dtype=tf.float32, name='advantages')

                    value_loss = tf.reduce_sum(tf.square(self.target_v - tf.reshape(self.value, [-1])))
                    policy_loss = tf.reduce_sum(
                        tf.square(self.actions - self.policy)
                        * self.advantages
                    )
                    loss = policy_loss - value_loss

                    # Get gradients from local network using local losses
                    local_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope)
                    gradients = tf.gradients(loss, local_vars)
                    var_norms = tf.global_norm(local_vars)
                    grads, grad_norms = tf.clip_by_global_norm(gradients, CLIP_NORM)

                    # Apply local gradients to global network
                    global_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, 'global')
                    self.apply_grads = trainer.apply_gradients(zip(grads, global_vars))

                if summary_level >= 1:
                    tf.summary.scalar('loss/value-loss', value_loss)
                    tf.summary.scalar('loss/policy-loss', policy_loss)
                    tf.summary.scalar('loss/grad-norm', grad_norms)
                    tf.summary.scalar('loss/var-norm', var_norms)

        self.noop = tf.no_op()
        self.merged_summaries = tf.summary.merge_all(tf.GraphKeys.SUMMARIES)