"""Track 1 of an archetype rework: structure from the data (docs §5.3 step 2).

Single UMAP + HDBSCAN runs are unstable on small pools, so this runs many of
them (parameter grid x bootstrap subsamples) and records how often each pair
of jobs lands in the same cluster (co-association). The final clusters come
from average-linkage clustering of that co-association matrix; groups smaller
than MIN_SIZE become outliers. Stability = mean co-association inside a cluster.
"""
import itertools
import threading
import warnings

import numpy as np
from sklearn.cluster import HDBSCAN, AgglomerativeClustering

N_NEIGHBORS = (5, 8, 12)
N_COMPONENTS = (5, 8)
MIN_CLUSTER = (3, 4, 5)
SEEDS = (0, 1, 2)
SUBSAMPLE = 0.8
# Numba's default threading layer aborts the whole process when two threads run
# UMAP at once (e.g. two Classify page loads, or a page load during a rework).
UMAP_LOCK = threading.Lock()
LINK_THRESHOLD = 0.55  # distance (1 - co-association) at which groups stop merging
MIN_SIZE = 3


def _one_run(x: np.ndarray, idx: np.ndarray, n_neighbors: int, n_components: int, min_cluster: int, seed: int) -> np.ndarray:
    import umap

    sub = x[idx]
    nn = max(2, min(n_neighbors, len(sub) - 1))
    with UMAP_LOCK, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        emb = umap.UMAP(n_neighbors=nn, n_components=min(n_components, len(sub) - 2), metric="cosine",
                        min_dist=0.0, random_state=seed).fit_transform(sub)
    return HDBSCAN(min_cluster_size=min_cluster, min_samples=2).fit_predict(emb)


def run(x: np.ndarray, progress=None) -> dict:
    n = len(x)
    together = np.zeros((n, n))
    sampled = np.zeros((n, n))
    clustered = np.zeros(n)
    seen = np.zeros(n)
    grid = list(itertools.product(N_NEIGHBORS, N_COMPONENTS, MIN_CLUSTER, SEEDS))
    rng = np.random.default_rng(42)
    for i, (nn, nc, mc, seed) in enumerate(grid):
        idx = np.sort(rng.choice(n, size=max(MIN_SIZE + 2, int(n * SUBSAMPLE)), replace=False))
        labels = _one_run(x, idx, nn, nc, mc, seed)
        seen[idx] += 1
        clustered[idx[labels >= 0]] += 1
        same = (labels[:, None] == labels[None, :]) & (labels[:, None] >= 0)
        sampled[np.ix_(idx, idx)] += 1
        together[np.ix_(idx, idx)] += same
        if progress and i % 9 == 8:
            progress(f"Track 1: clustering run {i + 1}/{len(grid)}")
    coassoc = np.divide(together, sampled, out=np.zeros_like(together), where=sampled > 0)
    np.fill_diagonal(coassoc, 1.0)

    labels = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="average",
                                     distance_threshold=LINK_THRESHOLD).fit_predict(1.0 - coassoc)
    final = -np.ones(n, dtype=int)
    next_id = 0
    for lab in sorted(set(labels), key=lambda l: -(labels == l).sum()):
        members = np.where(labels == lab)[0]
        if len(members) >= MIN_SIZE:
            final[members] = next_id
            next_id += 1

    stability = {}
    for c in range(next_id):
        m = np.where(final == c)[0]
        pairs = coassoc[np.ix_(m, m)][np.triu_indices(len(m), k=1)]
        stability[c] = round(float(pairs.mean()), 3) if len(pairs) else 1.0
    return {
        "labels": final,
        "coassoc": coassoc,
        "stability": stability,
        "clustered_rate": np.divide(clustered, seen, out=np.zeros_like(clustered), where=seen > 0),
        "n_runs": len(grid),
    }


def layout_2d(x: np.ndarray) -> np.ndarray:
    """2D coordinates for the Classify page map (one fixed-seed UMAP run)."""
    import umap

    with UMAP_LOCK, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return umap.UMAP(n_neighbors=max(2, min(10, len(x) - 1)), n_components=2, metric="cosine",
                         min_dist=0.15, random_state=42).fit_transform(x)
