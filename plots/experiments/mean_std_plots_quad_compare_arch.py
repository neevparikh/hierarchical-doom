import argparse
import os
import pickle
import sys
from os.path import join
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import ticker
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

from plots.plot_utils import set_matplotlib_params, ORANGE, BLUE
from utils.utils import ensure_dir_exists
from matplotlib.ticker import FuncFormatter
from scipy.signal import savgol_filter

set_matplotlib_params()

PAGE_WIDTH_INCHES = 8.2
FULL_PAGE_WIDTH = 1.4 * PAGE_WIDTH_INCHES
HALF_PAGE_WIDTH = FULL_PAGE_WIDTH / 2

plt.rcParams['figure.figsize'] = (HALF_PAGE_WIDTH, 3.5)  # (2.5, 2.0) 7.5， 4
plt.rcParams["axes.formatter.limits"] = [-1, 1]

NUM_AGENTS = 8
EPISODE_DURATION = 16  # seconds
TIME_METRIC_COLLISION = 60  # ONE MINUTE
COLLISIONS_SCALE = ((TIME_METRIC_COLLISION / EPISODE_DURATION) /
                    NUM_AGENTS) * 2  # times two because 1 collision = 2 drones collided

CRASH_GROUND_SCALE = (-1.0 / EPISODE_DURATION)

PLOTS = [
    dict(key='0_aux/avg_rewraw_pos',
         name='Avg. distance to the target',
         label='Avg. distance, meters',
         coeff=-1.0 / EPISODE_DURATION,
         logscale=True,
         clip_min=0.2,
         y_scale_formater=[0.2, 0.5, 1.0, 2.0]),
    dict(key='0_aux/avg_num_collisions_Scenario_ep_rand_bezier',
         name='Avg. collisions for pursuit evasion (bezier)',
         label='Number of collisions',
         logscale=True,
         coeff=COLLISIONS_SCALE,
         clip_min=0.05),
    dict(key='0_aux/avg_num_collisions_after_settle',
         name='Avg. collisions between drones per minute',
         label='Number of collisions',
         logscale=True,
         coeff=COLLISIONS_SCALE,
         clip_min=0.05),
    dict(key='0_aux/avg_num_collisions_Scenario_static_same_goal',
         name='Avg. collisions for static same goal',
         label='Number of collisions',
         logscale=True,
         coeff=COLLISIONS_SCALE,
         clip_min=0.05),
]

PLOT_STEP = int(5e6)
TOTAL_STEP = int(1e9 + 10000)

# 'blue': '#1F77B4', 'orange': '#FF7F0E', 'green': '#2CA02C', 'red': '#d70000'
COLOR = ['#1F77B4', '#FF7F0E', '#2CA02C', '#d70000']


def extract(experiments):
    scalar_accumulators = [
        EventAccumulator(experiment_dir).Reload().scalars for experiment_dir in experiments
    ]

    # Filter non event files
    scalar_accumulators = [
        scalar_accumulator for scalar_accumulator in scalar_accumulators
        if scalar_accumulator.Keys()
    ]

    # Get and validate all scalar keys
    all_keys = [
        tuple(sorted(scalar_accumulator.Keys())) for scalar_accumulator in scalar_accumulators
    ]
    assert len(set(all_keys)) == 1, \
        "All runs need to have the same scalar keys. There are mismatches in {}".format(all_keys)

    keys = all_keys[0]
    all_scalar_events_per_key = [[
        scalar_accumulator.Items(key) for scalar_accumulator in scalar_accumulators
    ] for key in keys]

    # Get and validate all steps per key
    x_per_key = [[
        tuple(scalar_event.step
              for scalar_event in sorted(scalar_events))
        for scalar_events in sorted(all_scalar_events)
    ]
                 for all_scalar_events in all_scalar_events_per_key]

    plot_step = PLOT_STEP
    all_steps_per_key = [[
        tuple(int(step_id)
              for step_id in range(0, TOTAL_STEP, plot_step))
        for _ in sorted(all_scalar_events)
    ]
                         for all_scalar_events in all_scalar_events_per_key]

    for i, all_steps in enumerate(all_steps_per_key):
        assert len(set(
            all_steps)) == 1, "For scalar {} the step numbering or count doesn't match. Step count for all runs: {}".format(
            keys[i], [len(steps) for steps in all_steps])

    steps_per_key = [all_steps[0] for all_steps in all_steps_per_key]

    # Get values per step per key
    values_per_key = [[[scalar_event.value
                        for scalar_event in scalar_events]
                       for scalar_events in all_scalar_events]
                      for all_scalar_events in all_scalar_events_per_key]

    interpolated_keys = dict()
    for tmp_id in range(len(PLOTS)):
        key_idx = keys.index(PLOTS[tmp_id]['key'])
        values = values_per_key[key_idx]

        x = steps_per_key[key_idx]
        x_steps = x_per_key[key_idx]

        interpolated_y = [[] for _ in values]

        for i in range(len(values)):
            idx = 0

            tmp_min_step = min(len(x_steps[i]), len(values[i]))
            values[i] = values[i][2:tmp_min_step]
            x_steps[i] = x_steps[i][2:tmp_min_step]

            assert len(x_steps[i]) == len(values[i])
            for x_idx in x:
                while idx < len(x_steps[i]) - 1 and x_steps[i][idx] < x_idx:
                    idx += 1

                if x_idx == 0:
                    interpolated_value = values[i][idx]
                elif idx < len(values[i]) - 1:
                    interpolated_value = (values[i][idx] + values[i][idx + 1]) / 2
                else:
                    interpolated_value = values[i][idx]

                interpolated_y[i].append(interpolated_value)
            assert len(interpolated_y[i]) == len(x)

        print(interpolated_y[0][:30])

        interpolated_keys[PLOTS[tmp_id]['key']] = (x, interpolated_y)

    return interpolated_keys


def aggregate(path, subpath, experiments, ax, legend_name, group_id):
    print("Started aggregation {}".format(path / subpath))

    curr_dir = os.path.dirname(os.path.abspath(__file__))
    cache_dir = join(curr_dir, 'cache')
    cache_env = join(cache_dir, subpath)

    if os.path.isdir(cache_env):
        with open(join(cache_env, f'{subpath}.pickle'), 'rb') as fobj:
            interpolated_keys = pickle.load(fobj)
    else:
        cache_env = ensure_dir_exists(cache_env)
        interpolated_keys = extract(experiments=experiments)
        with open(join(cache_env, f'{subpath}.pickle'), 'wb') as fobj:
            pickle.dump(interpolated_keys, fobj)

    for i, key in enumerate(interpolated_keys.keys()):
        plot(i, interpolated_keys[key], ax[i], legend_name, group_id)


# def plot(env, key, interpolated_key, ax, count):
def plot(index, interpolated_key, ax, legend_name, group_id):
    params = PLOTS[index]

    # set title
    title_text = params['name']
    ax.set_title(title_text, fontsize=8)
    if index >= 2:
        ax.set_xlabel('Simulation steps')

    x, y = interpolated_key
    y_np = [np.array(yi) for yi in y]
    y_np = np.stack(y_np)

    logscale = params.get('logscale', False)
    if logscale:
        ax.set_yscale('log', base=2)
        ax.yaxis.set_minor_locator(ticker.NullLocator())  # no minor ticks

        def scientific(x, pos):
            # x:  tick value - ie. what you currently see in yticks
            # pos: a position - ie. the index of the tick (from 0 to 9 in this example)
            return '%.2f' % x

        scientific_formatter = FuncFormatter(scientific)
        ax.yaxis.set_major_formatter(scientific_formatter)

        # ax.yaxis.set_major_formatter(scalar_formatter)  # set regular formatting

    coeff = params.get('coeff', 1.0)
    y_np *= coeff

    mutate = params.get('mutate', None)
    if mutate:
        for i in range(y_np.shape[1]):
            y_np[:, i] = mutate(y_np[:, i])

    # y_np = savgol_filter(y_np, 5, 2)

    y_mean = np.mean(y_np, axis=0)
    y_std = np.std(y_np, axis=0)
    y_plus_std = y_mean + y_std
    y_minus_std = y_mean - y_std

    clip_max = params.get('clip_max', None)
    if clip_max:
        y_mean = np.minimum(y_mean, clip_max)
        y_plus_std = np.minimum(y_plus_std, clip_max)
        y_minus_std = np.minimum(y_minus_std, clip_max)

    clip_min = params.get('clip_min', None)
    if clip_min:
        y_mean = np.maximum(y_mean, clip_min)
        y_plus_std = np.maximum(y_plus_std, clip_min)
        y_minus_std = np.maximum(y_minus_std, clip_min)

    def mkfunc(x, pos):
        if x >= 1e9:
            return '%dB' % int(x * 1e-9)
        elif x >= 1e6:
            return '%dM' % int(x * 1e-6)
        elif x >= 1e3:
            return '%dK' % int(x * 1e-3)
        else:
            return '%d' % int(x)

    mkformatter = matplotlib.ticker.FuncFormatter(mkfunc)
    ax.xaxis.set_major_formatter(mkformatter)

    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['bottom'].set_linewidth(1.0)

    label = params.get('label')
    if label:
        ax.set_ylabel(label, fontsize=8)
        # hide tick of axis
        ax.xaxis.tick_bottom()

    ax.yaxis.tick_left()
    ax.tick_params(which='major', length=0)

    ax.grid(color='#B3B3B3', linestyle='-', linewidth=0.25, alpha=0.2)
    # ax.ticklabel_format(style='plain', axis='y', scilimits=(0, 0))

    lw = 1.0
    ax.fill_between(x,
                    y_minus_std,
                    y_plus_std,
                    color=COLOR[group_id],
                    alpha=0.25,
                    antialiased=True,
                    linewidth=0.0)
    ax.plot(x, y_mean, color=COLOR[group_id], label=legend_name, linewidth=lw, antialiased=True)
    # ax.legend()


def hide_tick_spine(ax):
    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.tick_params(labelcolor='w', top=False, bottom=False, left=False, right=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path',
                        type=str,
                        help='main path for tensorboard files',
                        default=os.getcwd())
    parser.add_argument(
        '--output',
        type=str,
        help='aggregation can be saves as tensorboard file (summary) or as table (csv)',
        default='csv')

    args = parser.parse_args()
    path = Path(args.path)

    if not path.exists():
        raise argparse.ArgumentTypeError('Parameter {} is not a valid path'.format(path))

    subpaths = sorted(os.listdir(path))
    legend_name = sorted(["ATTENTION", "DEEPSETS", "MLP"])
    all_experiment_dirs = {}
    for subpath in subpaths:
        if subpath not in all_experiment_dirs:
            all_experiment_dirs[subpath] = []

        for filename in Path(args.path + "/" + subpath).rglob('*.tfevents.*'):
            experiment_dir = os.path.dirname(filename)
            all_experiment_dirs[subpath].append(experiment_dir)

    if args.output not in ['summary', 'csv']:
        raise argparse.ArgumentTypeError("Parameter {} is not summary or csv".format(args.output))

    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2)
    ax = (ax1, ax2, ax3, ax4)
    for i in range(len(all_experiment_dirs)):
        aggregate(path, subpaths[i], all_experiment_dirs[subpaths[i]], ax, legend_name[i], i)

        # if i != 0:
    handles, labels = ax[-1].get_legend_handles_labels()
    lgd = fig.legend(handles,
                     labels,
                     bbox_to_anchor=(0.15, 0.85, 0.8, 0.2),
                     loc='upper left',
                     ncol=3,
                     mode="expand",
                     prop={'size': 6})
    lgd.set_in_layout(True)

    plt.tight_layout(pad=1.0)
    plt.subplots_adjust(wspace=0.25, hspace=0.3)
    # plt.margins(0, 0)

    plt.savefig(os.path.join(os.getcwd(), f'../final_plots/quads_compare_arch.pdf'),
                format='pdf',
                bbox_inches='tight',
                pad_inches=0.01)

    return 0


if __name__ == '__main__':
    sys.exit(main())
