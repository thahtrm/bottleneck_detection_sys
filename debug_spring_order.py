"""Debug: tìm node vi phạm "Trying to update memory to time in the past" trên Spring.

Replay training loop của train_self_supervised.py (cùng config) với
instrumentation trên memory updater để in ra node + timestamps vi phạm.
Chạy: python3 debug_spring_order.py [n_batches]
"""
import math
import sys
import numpy as np
import torch

N_BATCHES = int(sys.argv[1]) if len(sys.argv) > 1 else 50

from utils.data_processing import get_data, compute_time_statistics
from utils.utils import get_neighbor_finder, RandEdgeSampler
from model.tgn import TGN
from modules.memory_updater import SequenceMemoryUpdater

DATA = "Spring"
BATCH_SIZE = 128
NUM_NEIGHBORS = 10
N_HEADS = 4
N_LAYERS = 2
MESSAGE_DIM = 64
MEMORY_DIM = 64
BACKPROP_EVERY = 4
DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

node_feats, edge_feats, full_data, train_data, val_data, test_data, nval, ntest = get_data(DATA)

# đúng như train_self_supervised.py: get_neighbor_finder(data, args.uniform=False)
train_ngh_finder = get_neighbor_finder(train_data, False)
full_ngh_finder = get_neighbor_finder(full_data, False)
train_rand_sampler = RandEdgeSampler(train_data.sources, train_data.destinations)

mean_time_shift_src, std_time_shift_src, mean_time_shift_dst, std_time_shift_dst = \
  compute_time_statistics(full_data.sources, full_data.destinations, full_data.timestamps)

tgn = TGN(neighbor_finder=train_ngh_finder, node_features=node_feats,
          edge_features=edge_feats, device=DEVICE,
          n_layers=N_LAYERS, n_heads=N_HEADS, dropout=0.1, use_memory=True,
          message_dimension=MESSAGE_DIM, memory_dimension=MEMORY_DIM,
          memory_update_at_start=True, embedding_module_type="graph_attention",
          message_function="mlp", aggregator_type="last", memory_updater_type="gru",
          n_neighbors=NUM_NEIGHBORS,
          mean_time_shift_src=mean_time_shift_src, std_time_shift_src=std_time_shift_src,
          mean_time_shift_dst=mean_time_shift_dst, std_time_shift_dst=std_time_shift_dst)
optimizer = torch.optim.Adam(tgn.parameters(), lr=0.001)
criterion = torch.nn.BCELoss()

# ---- instrumentation -------------------------------------------------------
orig_get_updated = SequenceMemoryUpdater.get_updated_memory
orig_update = SequenceMemoryUpdater.update_memory

def diag(name, self, unique_node_ids, unique_messages, timestamps):
    if len(unique_node_ids) > 0:
        last = self.memory.get_last_update(unique_node_ids)
        bad = (last > timestamps).nonzero(as_tuple=False).flatten().tolist()
        if bad:
            for b in bad[:8]:
                nid = unique_node_ids[b]
                print(f"[{name}] VIOLATION node={nid} last_update={float(last[b]):.3f} "
                      f"new_ts={float(timestamps[b]):.3f} diff={float(last[b]-timestamps[b]):.3f}", flush=True)
            print(f"[{name}] total bad: {len(bad)}/{len(unique_node_ids)}", flush=True)
            nid = unique_node_ids[bad[0]]
            msgs = self.memory.messages.get(nid, [])
            print(f"[{name}] stored msgs for node {nid}: ts={[round(float(m[1]), 1) for m in msgs]}", flush=True)
            raise SystemExit(42)
    if name == "get_updated":
        return orig_get_updated(self, unique_node_ids, unique_messages, timestamps)
    return orig_update(self, unique_node_ids, unique_messages, timestamps)

def patched_get_updated(self, unique_node_ids, unique_messages, timestamps):
    return diag("get_updated", self, unique_node_ids, unique_messages, timestamps)

def patched_update(self, unique_node_ids, unique_messages, timestamps):
    return diag("update", self, unique_node_ids, unique_messages, timestamps)

SequenceMemoryUpdater.get_updated_memory = patched_get_updated
SequenceMemoryUpdater.update_memory = patched_update
# ---------------------------------------------------------------------------

tgn.memory.__init_memory__()
num_instance = len(train_data.sources)
num_batch = math.ceil(num_instance / BATCH_SIZE)

tgn.train()
for k in range(0, min(num_batch, N_BATCHES), BACKPROP_EVERY):
    loss = 0
    optimizer.zero_grad()
    for j in range(BACKPROP_EVERY):
        batch_idx = k + j
        if batch_idx >= num_batch:
            continue
        s = batch_idx * BATCH_SIZE
        e = min(num_instance, s + BATCH_SIZE)
        src, dst = train_data.sources[s:e], train_data.destinations[s:e]
        edge_idxs_b = train_data.edge_idxs[s:e]
        ts_b = train_data.timestamps[s:e]
        size = len(src)
        _, neg = train_rand_sampler.sample(size)
        pos_label = torch.ones(size, dtype=torch.float, device=DEVICE)
        neg_label = torch.zeros(size, dtype=torch.float, device=DEVICE)
        pos_prob, neg_prob = tgn.compute_edge_probabilities(src, dst, neg, ts_b, edge_idxs_b, NUM_NEIGHBORS)
        loss += criterion(pos_prob.reshape(-1), pos_label) + criterion(neg_prob.reshape(-1), neg_label)
        if batch_idx < 6 or batch_idx % 200 == 0:
            print(f"batch {batch_idx}: ts [{float(ts_b.min()):.1f} .. {float(ts_b.max()):.1f}] "
                  f"uniq_u={len(set(src))} uniq_i={len(set(dst))}", flush=True)
    loss /= BACKPROP_EVERY
    loss.backward()
    optimizer.step()
    tgn.memory.detach_memory()

print("OK — không vi phạm trong số batch đã chạy", flush=True)
