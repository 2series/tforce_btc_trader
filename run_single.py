import tensorflow as tf
import numpy as np
from tensorforce.execution import Runner
import agent_conf, data
from experiments import confs

from queue import Queue
from threading import Thread

TEST = True

def run_experiment(q):
    while True:
        conf = q.get()
        conf['conf'].update(
            tf_session_config=tf.ConfigProto(
                gpu_options=tf.GPUOptions(per_process_gpu_memory_fraction=.2 if TEST else .6)
            ),
        )
        conf = agent_conf.conf(
            conf['conf'],
            agent_type='PPOAgent',
            mods=conf['name'],
            # env_args=dict(log_states=True, is_main=True, log_results=False),
            env_args=dict(is_main=True, log_results=True, scale_features=True)
        )
        print(conf['agent_name'])
        runner = Runner(agent=conf['agent'], environment=conf['env'])
        runner.run(episodes=100)
        print(conf['agent_name'], 'done')
        q.task_done()


q = Queue(0)
num_threads = 1 if TEST else 8
for i in range(num_threads):
  worker = Thread(target=run_experiment, args=(q,))
  worker.setDaemon(True)
  worker.start()

for c in confs: q.put(c)
q.join()