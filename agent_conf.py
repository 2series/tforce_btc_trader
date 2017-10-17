from tensorforce import Configuration, TensorForceError, agents, models
from tensorforce.core.networks import layered_network_builder

from btc_env.btc_env import BitcoinEnvTforce

AGENT_TYPE = 'PPOAgent'
STEPS = 2048 * 3 + 3


def baseline(**kwargs):
    b = dict(baseline = dict(
        type="mlp",
        sizes=[128, 128],
        epochs=10,
        update_batch_size=512,  # 1024
        learning_rate=.001
    ))
    b['baseline'].update(**kwargs)
    return b


def network(layers, a='elu', d=None, l2=.001, l1=.005):
    arr = []
    if d: arr.append(dict(type='dropout', dropout=d))
    for type, size in layers:
        if type == 'D':
            arr.append(dict(type='dense2', size=size, dropout=d, activation=a))
        elif type == 'd':
            arr.append(dict(
                type='dense',
                size=size,
                activation=a,
                l1_regularization=l1,
                l2_regularization=0. if d else l2)
            )
            if d: arr.append(dict(type='dropout', dropout=d))
        elif type == 'L':
            arr.append(dict(type='lstm', size=size, dropout=d))
    return arr


nets = {
    '1x': [('L',64), ('L',64), ('d',64)],
    '2x': [('L',128), ('L',128), ('d',64)],
    '3x': [('L',256), ('L',256), ('d',192), ('d',128)],
    '4x': [('d',128), ('L',256), ('L',256), ('d',192), ('d',128)],
    '5x': [('L',512), ('L',512), ('d',256), ('d',128)],
    '6x': [('d',192), ('L',512), ('L',512), ('d',256), ('d',128)],
}
net_default = nets['3x']
del nets['3x']
network_experiments = dict(k='network', v=[{'k': k, 'v': {'network': v}} for k, v in nets.items()])
dropout_experiments = dict(k='dropout', v=[
    dict(k='.2', v=dict(network=network(net_default, d=.2))),
    dict(k='.5', v=dict(network=network(net_default, d=.5))),
])
activation_experiments = dict(k='activation', v=[
    dict(k='tanh', v=dict(network=network(net_default, a='tanh'))),
    dict(k='selu', v=dict(network=network(net_default, a='selu'))),
    dict(k='relu', v=dict(network=network(net_default, a='relu')))
])
main_experiment = dict(k='main', v=[dict(k='-', v=dict())])

if AGENT_TYPE in ['PPOAgent', 'VPGAgent', 'TRPOAgent']:
    confs = [
        main_experiment,
        dict(k='epochs', v=[
            dict(k='1', v=dict(epochs=1)),
            dict(k='5', v=dict(epochs=5)),  # >5 bad
        ]),
        dict(k='discount', v=[
            dict(k='.95', v=dict(discount=.95)),
            dict(k='.99', v=dict(discount=.99)),
        ]),
        dropout_experiments,
        network_experiments,
        activation_experiments,
        dict(k='learning_rate', v=[
            dict(k='1e-7', v=dict(learning_rate=1e-7)),
            dict(k='1e-5', v=dict(learning_rate=1e-5)),
        ]),
        dict(k='batch', v=[
            dict(k='b2048.o1024', v=dict(batch_size=2048, optimizer_batch_size=1024)),
            dict(k='b1024.o128', v=dict(batch_size=1024, optimizer_batch_size=128)),
        ]),
        dict(k='keep_last', v=[
            dict(k='False', v=dict(keep_last=False)),
        ]),
        dict(k='random_sampling', v=[
            dict(k='False', v=dict(random_sampling=False)),
        ]),
        dict(k='gae_rewards', v=[
            dict(k='True', v=dict(gae_rewards=True)),  # winner=False
        ]),
        dict(k='optimizer', v=[
            dict(k='adam', v=dict(optimizer='adam')),
        ]),
        # dict(k='baseline', v=[
        #     dict(k='2x64', v=baseline(sizes=[64, 64])),
        #     dict(k='2x256', v=baseline(sizes=[256, 256])),
        #     dict(k='epochs5', v=baseline(epochs=5)),
        #     dict(k='update_batch_size128', v=baseline(update_batch_size=128)),
        #     dict(k='update_batch_size1024', v=baseline(update_batch_size=1024)),
        #     dict(k='learning_rate.1e-6', v=baseline(learning_rate=1e-6)),
        # ]),
    ]

elif AGENT_TYPE in ['NAFAgent']:
    confs = [
        main_experiment,
        dict(k='repeat_update', v=[
            dict(k='4', v=dict(repeat_update=4))
        ]),
        dropout_experiments,
        network_experiments,
        activation_experiments,
        dict(k='clip_loss', v=[
            dict(k='.5', v=dict(clip_loss=.5)),
            dict(k='0.', v=dict(clip_loss=0.)),
        ]),
        dict(k='exploration', v=[
            dict(k='ornstein_uhlenbeck_no_params', v=dict(exploration="ornstein_uhlenbeck")),
            dict(k='epsilon_decay', v=dict(exploration=dict(
                type="epsilon_decay",
                epsilon=1.0,
                epsilon_final=0.1,
                epsilon_timesteps=1e6
            ))),
        ]),
        dict(k='memory_capacity', v=[
            dict(k='5e4', v=dict(memory_capacity=50000, first_update=500)),
            dict(k='1e6', v=dict(memory_capacity=1000000, first_update=10000)),
        ]),
        dict(k='target_update_frequency', v=[
            dict(k='1', v=dict(target_update_frequency=1)),
            dict(k='20', v=dict(target_update_frequency=20)),
        ]),
        dict(k='update_target_weight', v=[
            dict(k='1', v=dict(update_target_weight=1.))
        ]),
        dict(k='update_frequency', v=[  # maybe does nothing (since target_update_frequency used)
            dict(k='1', v=dict(update_frequency=1))
        ]),
        dict(k='batch_size', v=[
            dict(k='100', v=dict(batch_size=100)),
            dict(k='1', v=dict(batch_size=1)),
        ]),
        dict(k='learning_rate', v=[
            dict(k='1e-6', v=dict(learning_rate=1e-6)),
            dict(k='1e-7', v=dict(learning_rate=1e-7)),
        ]),
        # dict(k='memory', v=[  # loser
        #     dict(k='prioritized_replay', v=dict(memory='prioritized_replay')),
        # ]),
    ]

elif AGENT_TYPE in ['DQNAgent', 'DQNNstepAgent']:
    prio_replay_batch = 16
    confs = [
        main_experiment,
        dict(k='discount', v=[
            dict(k='.95', v=dict(discount=.95)),
            dict(k='.99', v=dict(discount=.99)),
        ]),
        dict(k="target_update_frequency", v=[
            dict(k='5000', v=dict(target_update_frequency=5000))
        ]),
        dict(k='update_target_weight', v=[
            dict(k='.001', v=dict(update_target_weight=.001)),
        ]),
        dropout_experiments,
        network_experiments,
        activation_experiments,
        dict(k='batch_size', v=[
            dict(k='100', v=dict(batch_size=100))
        ]),
        dict(k='batch_combo', v=[
            dict(k='8', v=dict(
                batch_size=8,
                memory_capacity=800,
                first_update=80,
                target_update_frequency=20,
            )),
            dict(k='16', v=dict(
                batch_size=16,
                memory_capacity=800,
                first_update=80,
                target_update_frequency=20,
            )),
        ]),
        dict(k='reward_preprocessing', v=[
            dict(k='clip', v=dict(reward_preprocessing=[dict(type='clip', min=-1, max=1)]))
        ]),
        dict(k='learning_rate', v=[
            dict(k='.004', v=dict(learning_rate=.004)),
            dict(k='.0001', v=dict(learning_rate=.0001)),
        ]),
        dict(k="repeat_update", v=[
           dict(k='4', v=dict(repeat_update=4)),
        ]),
        dict(k='clip_loss', v=[
            dict(k='1.', v=dict(clip_loss=1.)),
            dict(k='.5', v=dict(clip_loss=.5))
        ]),
        dict(k='memory', v=[
            dict(k='replay:False', v=dict(memory=dict(type='replay', random_sampling=False))),
            dict(k='prio-tforce', v=dict(
                memory='prioritized_replay',
                batch_size=8,
                memory_capacity=50,
                first_update=20,
                target_update_frequency=10,
            )),
            # dict(k='prio-custom', v=dict(
            #     memory='prioritized_replay',
            #     batch_size=prio_replay_batch,
            #     memory_capacity=int(prio_replay_batch * 6.25),
            #     first_update=int(prio_replay_batch * 2.5),
            #     target_update_frequency=int(prio_replay_batch * 1.25)
            # )),
            # # https://jaromiru.com/2016/11/07/lets-make-a-dqn-double-learning-and-prioritized-experience-replay/
            # dict(k='prio-blog', v=dict(
            #     memory='prioritized_replay',
            #     batch_size=32,
            #     memory_capacity=200000,
            #     first_update=int(32 * 2.5),
            #     target_update_frequency=10000
            # ))
        ]),
        dict(k="keep_last", v=[
           dict(k='True', v=dict(keep_last=True))
        ]),
        dict(k="exploration", v=[
            dict(k='epsilon_anneal', v=dict(
                type="epsilon_anneal",
                epsilon=1.0,
                epsilon_final=0.,
                epsilon_timesteps=1.5e6
            ))
        ]),
        # "discount": 0.99,
        # update_frequency=500,
    ]

    if AGENT_TYPE == 'DQNNstepAgent':
        confs += []
    elif AGENT_TYPE == 'DQNAgent':
        confs += [
            # dict(k='double_dqn', v=[dict(k='False', v=dict(double_dqn=False))])
        ]

confs = [
    dict(
        name=c['k'] + ':' + permu['k'],
        conf=permu['v']
    )
    for c in confs for permu in c['v']
]


def conf(overrides, name='main', env_args={}, no_agent=False):
    name = AGENT_TYPE + '|' + name
    agent_class = agents.agents[AGENT_TYPE]

    if 'env_args' in overrides:
        env_args.update(overrides['env_args'])
        del overrides['env_args']

    env = BitcoinEnvTforce(steps=STEPS, name=name, **env_args)

    conf = dict(
        tf_session_config=None,
        # tf_session_config=tf.ConfigProto(device_count={'GPU': 0}),
        # tf_session_config=tf.ConfigProto(gpu_options=tf.GPUOptions(per_process_gpu_memory_fraction=.2)),
        log_level="info",
        tf_saver=False,
        tf_summary=None,
        tf_summary_level=0,

        network=network(net_default),
        keep_last=True,
        learning_rate=1e-8,
        discount=.99,
        exploration=dict(
            type="epsilon_decay",
            epsilon=1.0,
            epsilon_final=0.,
            epsilon_timesteps=1.3e6
        ),
        optimizer="nadam", # winner=nadam
        states=env.states,
        actions=env.actions
    )

    if agent_class == agents.TRPOAgent:
        pass
    elif issubclass(agent_class.model, models.PolicyGradientModel):
        conf.update(
            batch_size=4096,  # batch_size must be > optimizer_batch_size
            optimizer_batch_size=2048,
            normalize_rewards=True,  # definite winner=True
            epochs=3,
            learning_rate=1e-6,  # -8 usually works better
            discount=.97,
            network=network(net_default, a='selu')
        )
    elif agent_class == agents.NAFAgent:
        conf.update(
            network=network(net_default, d=.4),
            batch_size=8,
            memory_capacity=800,
            first_update=80,
            exploration=dict(
                type="ornstein_uhlenbeck",
                sigma=0.2,
                mu=0,
                theta=0.15
            ),
            update_target_weight=.001,
            clip_loss=1.
        )
    elif agent_class == agents.DQNAgent:
        conf.update(
            double_dqn=True,

            # seeming winners, more testing desired
            # Wants network 4x or 5x, but maxes from mem-leak
            network=network(net_default, a='tanh'),
            batch_size=50,
            target_update_frequency=5000
        )
    elif agent_class == agents.DQNNstepAgent:
        conf.update(batch_size=8)
        # Investigate graphs: batch-8 setup, random_replay=False, 4x


    conf.update(overrides)
    conf['network'] = layered_network_builder(conf['network'])
    conf = Configuration(**conf)

    return dict(
        agent=None if no_agent else agent_class(config=conf),
        conf=conf,
        env=env,
        name=name
    )