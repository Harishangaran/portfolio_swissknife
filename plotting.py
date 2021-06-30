import numpy as np
import matplotlib.pyplot as plt
from matplotlib import cm

#set global style
plt.style.use('bmh')

def plot_returns(df, r_benchmark, ax = None, *args, **kwargs):
    if ax is None:
        ax = plt.gca()
        fig = plt.gcf()
        fig.set_figheight(10)
        fig.set_figwidth(13)

    ax.set_title('Cumulative Returns')

    labels = df.columns.to_list()
    labels += ['Benchmark']
    dates = df.index.to_list()

    ax.plot(dates, df, *args, **kwargs)
    ax.plot(dates, r_benchmark, alpha=0.8, c='gray', linestyle='--')
    ax.legend(labels)
    fig = plt.gcf()
    fig.tight_layout()
    return ax

def plot_weights(df, ax = None, *args, **kwargs):
    pass


def plot_stacked_weights(df, model: str, ax = None, *args, **kwargs):
    if ax is None:
        ax = plt.gca()
        fig = plt.gcf()

    ax.set_title(f"{model} weights structure")
    labels = df.columns.tolist()

    colormap = cm.get_cmap('tab20')
    colormap = colormap(np.linspace(0, 1, 20))

    cycle = plt.cycler("color", colormap)
    ax.set_prop_cycle(cycle)
    X = df.index.tolist()

    ax.stackplot(X, np.vstack(df.values.T), labels=labels, alpha=0.7, edgecolor="black")

    ax.set_ylim(0, 1)
    ax.set_xlim(0, X[-1])

    ticks_loc = ax.get_yticks().tolist()
    ax.set_yticks(ax.get_yticks().tolist())
    ax.set_yticklabels(["{:3.2%}".format(x) for x in ticks_loc])
    ax.grid(linestyle=":")
    n = int(np.ceil(len(labels) / 4))
    fig = plt.gcf()
    fig.tight_layout()
    return ax