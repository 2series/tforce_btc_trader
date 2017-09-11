from __future__ import absolute_import, division, print_function
import argparse, inspect, logging, os, sys, time, math
import tensorflow as tf
from six.moves import xrange, shlex_quote
from pprint import pprint

from tensorforce import Configuration, TensorForceError
from tensorforce.agents import VPGAgent, PPOAgent, TRPOAgent
from tensorforce.core.networks import layered_network_builder
from tensorforce.execution import Runner
from tensorforce.util import log_levels

from tforce_env import BitcoinEnv
from helpers import conn

STEPS = 10000
AGENT_NAME = 'PPOAgent'
agent_type = AGENT_NAME.split('|')[0]
env_args = dict(
    limit=STEPS, agent_type=agent_type, agent_name=AGENT_NAME,
    scale_features=True,
    punish_overdraft=True,
    absolute_reward=False
)


def my_network():
    """ Define full network since will be using batch_normalization and other special handling
    TODO incomplete. Need to run extra_update_ops from tf.GraphKeys.UPDATE_OPS (see p. 284)
    """
    n_inputs = 28*28
    n_hidden1 = 300
    n_hidden2 = 100
    n_outputs = 10

    X = tf.placeholder(tf.float32, shape=(None, n_inputs), name='X')

    training = tf.placeholder_with_default(False, shape=(), name='training')

    hidden1 = tf.layers.dense(X, n_hidden1, name='hidden1')
    bn1 = tf.layers.batch_normalization(hidden1, training=training, momentum=.9)
    bn1_act = tf.nn.elu(bn1)
    hidden2 = tf.layers.dense(bn1_act, n_hidden2, name='hidden2')
    bn2 = tf.layers.batch_normalization(hidden2, training=training, momentum=.9)
    bn2_act = tf.nn.elu(bn2)
    logits_before_bn = tf.layers.dense(bn2_act, n_outputs, name='outputs')
    logits = tf.layers.batch_normalization(logits_before_bn, training=training, momentum=.9)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('gym_id', help="ID of the gym environment")
    parser.add_argument('-e', '--episodes', type=int, default=500000, help="Number of episodes")
    parser.add_argument('-t', '--max-timesteps', type=int, default=STEPS, help="Maximum number of timesteps per episode")
    parser.add_argument('-w', '--num-workers', type=int, default=1, help="Number of worker agents")
    parser.add_argument('-m', '--monitor', help="Save results to this file")
    parser.add_argument('-M', '--mode', choices=['tmux', 'child'], default='tmux', help="Starter mode")
    parser.add_argument('-L', '--logdir', default='logs_async', help="Log directory")
    parser.add_argument('-C', '--is-child', action='store_true')
    parser.add_argument('-i', '--task-index', type=int, default=0, help="Task index")
    parser.add_argument('-K', '--kill', action='store_true', default=False, help="Kill runners")
    parser.add_argument('-D', '--debug', action='store_true', default=False, help="Show debug outputs")

    args = parser.parse_args()

    session_name = 'bitcoin_async'
    shell = '/bin/bash'

    kill_cmds = [
        "kill $( lsof -i:12222-{} -t ) > /dev/null 2>&1".format(12222 + args.num_workers),
        "tmux kill-session -t {}".format(session_name),
    ]
    if args.kill:
        os.system("\n".join(kill_cmds))
        return 0

    if not args.is_child:
        conn.execute("delete from episodes where agent_name='{}'".format(AGENT_NAME))

        # start up child processes
        target_script = os.path.abspath(inspect.stack()[0][1])

        def wrap_cmd(session, name, cmd):
            if isinstance(cmd, list):
                cmd = ' '.join(shlex_quote(str(arg)) for arg in cmd)
            if args.mode == 'tmux':
                return 'tmux send-keys -t {}:{} {} Enter'.format(session, name, shlex_quote(cmd))
            elif args.mode == 'child':
                return '{} > {}/{}.{}.out 2>&1 & echo kill $! >> {}/kill.sh'.format(
                    cmd, args.logdir, session, name, args.logdir
                )

        def build_cmd(index):
            cmd_args = [
                'CUDA_VISIBLE_DEVICES=',
                sys.executable, target_script,
                args.gym_id,
                '--is-child',
                '--num-workers', args.num_workers,
                '--task-index', index
            ]
            if args.debug:
                cmd_args.append('--debug')
            return cmd_args

        if args.mode == 'tmux':
            cmds = kill_cmds + ['tmux new-session -d -s {} -n ps'.format(session_name)]
        elif args.mode == 'child':
            cmds = ['mkdir -p {}'.format(args.logdir),
                    'rm -f {}/kill.sh'.format(args.logdir),
                    'echo "#/bin/bash" > {}/kill.sh'.format(args.logdir),
                    'chmod +x {}/kill.sh'.format(args.logdir)]
        cmds.append(wrap_cmd(session_name, 'ps', build_cmd(-1)))

        for i in xrange(args.num_workers):
            name = 'w_{}'.format(i)
            if args.mode == 'tmux':
                cmds.append('tmux new-window -t {} -n {} -d {}'.format(session_name, name, shell))
            cmds.append(wrap_cmd(session_name, name, build_cmd(i)))

        # add one PS call
        # cmds.append('tmux new-window -t {} -n ps -d {}'.format(session_name, shell))

        print("\n".join(cmds))

        os.system("\n".join(cmds))

        return 0

    ps_hosts = ['127.0.0.1:{}'.format(12222)]
    worker_hosts = []
    port = 12223
    for _ in range(args.num_workers):
        worker_hosts.append('127.0.0.1:{}'.format(port))
        port += 1
    cluster = {'ps': ps_hosts, 'worker': worker_hosts}
    cluster_spec = tf.train.ClusterSpec(cluster)
    device = ('/job:ps' if args.task_index == -1 else '/job:worker/task:{}/cpu:0'.format(args.task_index))

    environment = BitcoinEnv(**env_args)

    neurons = 150  # TODO experiment (32, 64, 128 all seem good - lower/better?)
    agent_config = dict(
        # tf_session_config=tf.ConfigProto(gpu_options=tf.GPUOptions(per_process_gpu_memory_fraction=.2)),

        # PolicyGradientModel
        batch_size=2048,  # TODO experiment
        gae_rewards=True,  # winner
        keep_last=True,
        baseline=dict(
            type="mlp",
            sizes=[neurons, neurons],  # losers: 2x256, winners: 2x128
            epochs=5,
            update_batch_size=128,
            learning_rate=.01
        ),

        # Network (Losers: L3x150, Winners: D150L2x150, L2x150, DLD)
        network=[
            dict(type='dense2', size=neurons, dropout=.2),  # combine attrs into attr-combos (eg VWAP)
            dict(type='lstm', size=neurons, dropout=.2),  # merge those w/ history
            dict(type='lstm', size=neurons, dropout=.2),  # merge those w/ history
            dict(type='dense2', size=neurons, dropout=.2),  # combine those into indicators (eg SMA)
        ],

        # Main
        discount=.97,  # TODO experiment
        exploration=dict(
            type="epsilon_decay",
            epsilon=1.0,
            epsilon_final=0.1,
            epsilon_timesteps=2e6
        ),
        # optimizer="adam",  # winner
        optimizer="nadam",
        states=environment.states,
        actions=environment.actions,

        # Async
        distributed=True,
        cluster_spec=cluster_spec,
        global_model=(args.task_index == -1),
        device=device,
        log_level="info",
        tf_saver=False,
        tf_summary=None,
        tf_summary_level=None,
        preprocessing=None
    )

    if agent_type == 'VPGAgent':
        agent_class = VPGAgent
        agent_config.update(dict(
            normalize_rewards=True,  # winner
            learning_rate=.01
        ))
    elif agent_type == 'PPOAgent':
        agent_class = PPOAgent
        # for some reason PPO configs all have activation=tanh, I need to read the paper
        for layer in agent_config['network']:
            if layer['type'] == 'dense': layer['activation'] = 'tanh'
        agent_config.update(dict(
            epochs=5,
            optimizer_batch_size=512,
            random_sampling=True,  # seems winner
            normalize_rewards=False,  # winner (even when scale_features=True)
            learning_rate=.001  # .001 best, currently speed-running
        ))
        pprint(agent_config)

    # Allow overrides to network above, then run it through configurator
    agent_config['network'] = layered_network_builder(agent_config['network'])
    agent_config = Configuration(**agent_config)

    logger = logging.getLogger(__name__)
    logger.setLevel(log_levels[agent_config.log_level])

    agent = agent_class(config=agent_config)

    logger.info("Starting distributed agent for OpenAI Gym '{gym_id}'".format(gym_id=args.gym_id))
    logger.info("Config:")
    logger.info(agent_config)

    runner = Runner(
        agent=agent,
        environment=environment,
        repeat_actions=1,
        cluster_spec=cluster_spec,
        task_index=args.task_index
    )

    report_episodes = args.episodes // 1000
    if args.debug:
        report_episodes = 1

    def episode_finished(r):
        if r.episode % report_episodes == 0:
            sps = r.total_timesteps / (time.time() - r.start_time)
            logger.info("Finished episode {ep} after {ts} timesteps. Steps Per Second {sps}".format(ep=r.episode, ts=r.timestep, sps=sps))
            logger.info("Episode reward: {}".format(r.episode_rewards[-1]))
            logger.info("Average of last 500 rewards: {}".format(sum(r.episode_rewards[-500:]) / 500))
            logger.info("Average of last 100 rewards: {}".format(sum(r.episode_rewards[-100:]) / 100))
        return True

    runner.run(args.episodes, args.max_timesteps, episode_finished=episode_finished)


if __name__ == '__main__':
    main()
