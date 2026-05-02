# Elasticsearch / OpenSearch 面试八股（速答版）

> 你列的这些点属于“检索引擎/ES(OpenSearch)”，不是 MySQL。下面按面试可背诵的方式整理：倒排索引、分片副本、BM25/kNN、RRF/MMR、refresh/flush，并补充常考：segment、translog、mapping/analyzer、filter vs query、doc_values 等。

---

## 1) 倒排索引：词 → 文档ID（快速检索）

### 一句话回答
倒排索引把“**词(term) → 出现在哪些文档(docID)**”建立映射，并在 posting list 里记录位置/频次等信息，使得按词检索时只需要访问相关文档集合，而不是全表扫描。

### 关键结构（说出来就加分）
- **term dictionary**：词典（可用 FST 压缩加速前缀/模糊匹配）。
- **posting list**：每个 term 对应的 docID 列表，通常还带：
  - `tf`（term frequency 词频）
  - `positions`（位置，用于短语查询）
  - `offsets`（高亮）
- **正排/列存**（doc_values）：用于聚合、排序、脚本字段访问，和倒排是两条体系。

### 常见追问
- **为什么 ES 适合全文检索？**：倒排 + 评分模型（BM25）+ 分词器 + segment 结构。
- **term vs keyword vs text？**：
  - `text` 会分词，走倒排；
  - `keyword` 不分词，适合精确匹配/聚合/排序。

---

## 2) 分片 / 副本：扩容 + 高可用

### 一句话回答
ES 把索引拆成多个 **primary shard（主分片）** 以水平扩展吞吐与容量；每个主分片可配置 **replica shard（副本）** 提高查询吞吐与容灾能力。

### 面试要点
- 写入：先到主分片，再复制到副本（成功条件取决于 `wait_for_active_shards` 等策略）。
- 查询：可在主/副本间负载均衡。
- 扩容：增加节点后 shard 重新分配（rebalancing）；**分片数通常不能随意改**（原生不支持直接 resize，需 split/shrink/reindex 等）。

### 常见追问
- **分片数怎么定？**
  - 经验上单分片不要太大（影响恢复/迁移），也别太碎（开销大）。更靠谱的答法：根据数据量、写入/查询 QPS、节点数量、恢复窗口做压测后定。
- **路由怎么定位到分片？**
  - 通常 `hash(_routing) % num_primary_shards`。

---

## 3) BM25 关键词检索、kNN 语义检索

### 3.1 BM25（关键词相关性）

#### 一句话回答
BM25 是基于 TF/IDF 的改进评分模型：词在文档中出现越频繁、在全库越稀有，得分越高，同时对文档长度做归一化。

#### 你可以写在纸上的公式（会背更强）
对查询 $q$ 与文档 $D$：
$$
score(D,q)=\sum_{t\in q} IDF(t)\cdot \frac{tf(t,D)\cdot (k_1+1)}{tf(t,D)+k_1\cdot (1-b+b\cdot \frac{|D|}{avgdl})}
$$
- $k_1$：控制 tf 饱和；$b$：长度归一化强度。

#### 典型追问
- **filter 和 query 区别？**
  - `query` 参与打分；`filter` 不打分、可缓存、适合条件过滤（比如状态、范围、权限）。

### 3.2 kNN（向量语义检索）

#### 一句话回答
kNN 用 embedding 向量表示语义，通过近似最近邻（ANN）在向量空间找最相近的 topK（相似度常用 cosine/dot/l2）。

#### 常见实现点（别说太细但要抓住核心）
- 典型 ANN：HNSW（图结构），用“以速度换精度”。
- 生产上常做 **hybrid**：先 filter（权限/时间）→ 向量召回 → 关键词补召回 → 融合排序。

#### ES 查询 DSL 示例（示意，字段名按你的 mapping）
```json
POST my_index/_search
{
  "size": 10,
  "query": {
    "bool": {
      "filter": [
        {"term": {"tenant_id": "t1"}},
        {"range": {"created_at": {"gte": "now-30d"}}}
      ],
      "should": [
        {"match": {"title": {"query": "向量检索 原理"}}}
      ]
    }
  },
  "knn": {
    "field": "content_vector",
    "query_vector": [0.12, 0.03, -0.44],
    "k": 100,
    "num_candidates": 1000
  }
}
```

> 面试提示：不同版本 ES/OpenSearch 对 `knn` 与混合写法支持略有差异，你只要讲清“关键词 + 向量 + filter + 融合”这条链路即可。

---

## 4) RRF 融合排序、MMR 去重

### 4.1 RRF（Reciprocal Rank Fusion）

#### 一句话回答
RRF 是一种稳定的“多路召回融合”方法：不直接用分数，而用各路结果的**名次**做融合，降低不同模型分数尺度不一致的问题。

#### 公式
对文档 $d$：
$$
RRF(d)=\sum_{i=1}^m \frac{1}{k + rank_i(d)}
$$
- $rank_i(d)$：文档在第 $i$ 路召回中的排名；没出现可视为无贡献。
- $k$：平滑常数（常取 10~60）。

#### 伪代码（可直接背）
```python
from collections import defaultdict

def rrf_fuse(rank_lists, k=60):
    # rank_lists: [ [doc1, doc2, ...], [doc3, doc1, ...], ... ]
    score = defaultdict(float)
    for lst in rank_lists:
        for r, doc_id in enumerate(lst, start=1):
            score[doc_id] += 1.0 / (k + r)
    return sorted(score.items(), key=lambda x: x[1], reverse=True)
```

### 4.2 MMR（Maximal Marginal Relevance，多样性/去重）

#### 一句话回答
MMR 在保证相关性的同时抑制重复：每次选一个“对查询相关，但与已选结果不太相似”的文档。

#### 公式（知道即可）
$$
MMR(d)=\lambda\cdot sim(d,q) - (1-\lambda)\cdot \max_{s\in S} sim(d,s)
$$
- $S$：已选集合；$\lambda$ 越大越偏相关性，越小越偏多样性。

#### 伪代码
```python
import math

def mmr_select(candidates, sim_to_query, sim_doc_doc, top_n=10, lam=0.7):
    # candidates: list of doc_id
    selected = []
    remaining = set(candidates)

    while remaining and len(selected) < top_n:
        best_doc, best_score = None, -math.inf
        for d in remaining:
            redundancy = 0.0
            if selected:
                redundancy = max(sim_doc_doc(d, s) for s in selected)
            score = lam * sim_to_query(d) - (1 - lam) * redundancy
            if score > best_score:
                best_doc, best_score = d, score
        selected.append(best_doc)
        remaining.remove(best_doc)

    return selected
```

---

## 5) 写入：refresh 刷段、flush 落盘

### 一句话回答
ES 写入是 **近实时（NRT）**：文档先写入内存 buffer 和 translog；**refresh** 会把内存里的数据生成新的 segment 并打开搜索，使其“可搜索”；**flush** 会把 translog 对应的数据持久化并生成新的 commit point，用于控制恢复成本。

### 你需要分清的 3 件事
- **refresh（让数据可被搜索）**：
  - 典型默认 1s（可配置 `refresh_interval`）。
  - refresh 会产生 segment，过于频繁会带来 segment 变多、合并压力变大。
- **flush（让恢复更轻）**：
  - 触发一次 Lucene commit，并清理旧 translog，降低 crash recovery 重放量。
- **segment merge（后台合并段）**：
  - 提升查询效率但消耗 IO/CPU；写入高峰 merge 压力大是常见瓶颈。

### 常见追问
- **为什么说 ES 近实时而不是实时？**：写入后到下一次 refresh 前不可被搜索。
- **如何提升写入吞吐？**：合理批量 bulk、增大 refresh_interval、控制 mapping、避免高基数聚合字段、优化分片布局等。

---

## 6) 常考补充（建议至少掌握这些“救命题”）

### 6.1 Mapping/Analyzer：分词与字段类型
- `text` 走 analyzer（分词），支持 match/phrase。
- `keyword` 精确匹配与聚合。
- 常见组合：`title` 为 `text`，同时加 `title.keyword` 用于聚合/排序。

### 6.2 Query vs Filter（性能与相关性）
- filter 不打分、可缓存，适合权限/状态/时间范围。
- query 打分，适合相关性检索。

### 6.3 高亮、短语、同义词
- 高亮依赖 offsets/positions。
- phrase 查询依赖 positions。
- 同义词扩展要注意召回变大导致噪声，通常配合 boost/融合。

### 6.4 常见问题定位（说出工具就像做过）
- 慢查询：profile、慢日志、hot threads。
- 写入积压：看 refresh/merge 压力、线程池队列、磁盘 IO。
- 分片倾斜：看 shard size、routing、热 key。

---

## 面试快速结尾句（可选）
- “我一般用 BM25 做关键词召回，用 kNN 做语义召回，最后用 RRF 融合，必要时再用 MMR 做结果去重/多样性。”
- “写入侧我会关注 refresh/merge 带来的 IO 压力，bulk 写入时适当调大 refresh_interval，保证吞吐。”
