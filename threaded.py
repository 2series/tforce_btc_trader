import argparse
import numpy as np
import tensorflow as tf
from tensorforce import Configuration
from tensorforce.agents import agents as agents_dict
from tensorforce.execution import ThreadedRunner
from tensorforce.execution.threaded_runner import WorkerAgent


from hypersearch import get_hypers, episode_finished, generate_and_save_hypers, env_from_flat

AGENT_K = 'ppo_agent'  # FIXME

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--experiment', type=int, default=0, help="Show debug outputs")
    parser.add_argument('-w', '--workers', type=int, default=4, help="Number of workers")
    parser.add_argument('-g', '--gpu-fraction', type=float, default=0., help="Per-process GPU memory fraction")
    args = parser.parse_args()

    while True:
        generate_and_save_hypers()

        main_agent = None
        agents, envs = [], []
        flat, hydrated, network = get_hypers(rand=True, from_db=False)
        if args.gpu_fraction:
            hydrated['tf_session_config'] = tf.ConfigProto(gpu_options=tf.GPUOptions(per_process_gpu_memory_fraction=args.gpu_fraction))

        for i in range(args.workers):
            envs.append(env_from_flat(flat))

            conf = hydrated.copy()
            # optionally overwrite epsilon final values
            if "exploration" in conf and "epsilon" in conf['exploration']['type']:
                # epsilon annealing is based on the global step so divide by the total workers
                # conf.exploration.epsilon_timesteps = conf.exploration.epsilon_timesteps // WORKERS
                conf['exploration']['epsilon_timesteps'] = conf['exploration']['epsilon_timesteps'] // 2
                if i != 0:  # for the worker which logs, let it expire
                    # epsilon final values are [0.5, 0.1, 0.01] with probabilities [0.3, 0.4, 0.3]
                    # epsilon_final = np.random.choice([0.5, 0.1, 0.01], p=[0.3, 0.4, 0.3])
                    epsilon_final = [.4, .1][i % 2]
                    conf['exploration']['epsilon_final'] = epsilon_final
            conf = Configuration(**conf)

            if i == 0:
                # let the first agent create the model, then create agents with a shared model
                main_agent = agent = agents_dict[AGENT_K](
                    states_spec=envs[0].states,
                    actions_spec=envs[0].actions,
                    network_spec=network,
                    config=conf
                )
            else:
                conf.default(main_agent.default_config)
                agent = WorkerAgent(
                    states_spec=envs[0].states,
                    actions_spec=envs[0].actions,
                    network_spec=network,
                    config=conf,
                    model=main_agent.model
                )
            agents.append(agent)

        # When ready, look at original threaded_ale for save/load & summaries
        threaded_runner = ThreadedRunner(agents, envs)
        threaded_runner.run(
            episodes=300*args.workers,
            # episode_finished=episode_finished(flat),
            summary_interval=args.workers,
            summary_report=episode_finished(flat)
        )
        [e.close() for e in envs]