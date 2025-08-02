# import os
# from typing import List, Dict, Any
# from dotenv import load_dotenv
# from FlagEmbedding import BGEM3FlagModel
# from sentence_transformers.cross_encoder import CrossEncoder
# from pinecone.grpc import PineconeGRPC as Pinecone
# from handler.query_enhancer import EnhancedQuery

# def hybrid_score_norm(dense, sparse, alpha: float):
#     if alpha < 0 or alpha > 1:
#         raise ValueError("Alpha must be between 0 and 1")
#     hs = {
#         'indices': sparse['indices'],
#         'values':  [v * (1 - alpha) for v in sparse['values']]
#     }
#     return [v * alpha for v in dense], hs

# class RetrieverAgent:
#     _embedder = None
#     _reranker = None
#     _pinecone_initialized = False
#     _index = None

#     def __init__(self):
#         if not RetrieverAgent._embedder:
#             RetrieverAgent._embedder = BGEM3FlagModel('BAAI/bge-m3', use_fp16=False)
#         if not RetrieverAgent._reranker:
#             RetrieverAgent._reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")
#         if not RetrieverAgent._pinecone_initialized:
#             load_dotenv()
#             api_key = os.getenv("PINECONE_API_KEY")
#             index_name = os.getenv("PINECONE_HYBRID_INDEX", "bajaj-test-1")
#             namespace = os.getenv("PINECONE_NAMESPACE", "bajaj-namespace")
#             pc = Pinecone(api_key=api_key)
#             RetrieverAgent._index = pc.Index(index_name)
#             RetrieverAgent._namespace = namespace
#             RetrieverAgent._pinecone_initialized = True

#     def _compose_search_query(self, enhanced_query: EnhancedQuery) -> str:
#         parts = [enhanced_query.raw_query] + enhanced_query.entities
#         if enhanced_query.keywords:
#             parts.extend(enhanced_query.keywords)
#         if enhanced_query.conditions:
#             parts.extend(enhanced_query.conditions)
#         return " ".join(filter(None, parts))

#     def retrieve_and_rerank(self, enhanced_query: EnhancedQuery, top_k_initial: int = 35, top_k_final: int = 5, alpha: float = 0.5) -> List[Dict[str, Any]]:
#         search_query = self._compose_search_query(enhanced_query)
#         result = RetrieverAgent._embedder.encode([search_query], return_dense=True, return_sparse=True)
#         dense_emb = result['dense_vecs'][0]
#         lw = result['lexical_weights'][0]
#         indices = [int(idx) for idx, val in lw.items() if float(val) != 0.0]
#         values = [float(val) for idx, val in lw.items() if float(val) != 0.0]
#         sparse = {'indices': indices, 'values': values}
#         # Apply alpha weighting if desired
#         hdense, hsparse = hybrid_score_norm(dense_emb, sparse, alpha)
#         try:
#             results = RetrieverAgent._index.query(
#                 vector=hdense,
#                 sparse_vector=hsparse,
#                 top_k=top_k_initial,
#                 namespace=RetrieverAgent._namespace,
#                 include_metadata=True
#             )["matches"]
#         except Exception as e:
#             print(f"Error querying Pinecone: {e}")
#             return []
#         if not results:
#             return []
#         seen_ids = set()
#         unique_results = []
#         for res in results:
#             chunk_id = res.get("id")
#             if chunk_id not in seen_ids:
#                 unique_results.append(res)
#                 seen_ids.add(chunk_id)
#         passages = [res["metadata"].get("text_content", "") for res in unique_results]
#         rerank_pairs = [[search_query, passage] for passage in passages]
#         scores = RetrieverAgent._reranker.predict(rerank_pairs)
#         reranked_results = []
#         for i, res in enumerate(unique_results):
#             reranked_results.append({
#                 "score": float(scores[i]),
#                 "metadata": res["metadata"]
#             })
#         reranked_results.sort(key=lambda x: x["score"], reverse=True)
#         return reranked_results[:top_k_final]

import os
from typing import List, Dict, Any
from dotenv import load_dotenv
from FlagEmbedding import BGEM3FlagModel
from pinecone.grpc import PineconeGRPC as Pinecone
from handler.query_enhancer import EnhancedQuery

def hybrid_score_norm(dense, sparse, alpha: float):
    if alpha < 0 or alpha > 1:
        raise ValueError("Alpha must be between 0 and 1")
    hs = {
        'indices': sparse['indices'],
        'values':  [v * (1 - alpha) for v in sparse['values']]
    }
    return [v * alpha for v in dense], hs

class RetrieverAgent:
    _embedder = None
    _pinecone_initialized = False
    _index = None

    def __init__(self):
        if not RetrieverAgent._embedder:
            RetrieverAgent._embedder = BGEM3FlagModel('BAAI/bge-m3', use_fp16=False)
        if not RetrieverAgent._pinecone_initialized:
            load_dotenv()
            api_key = os.getenv("PINECONE_API_KEY")
            index_name = os.getenv("PINECONE_HYBRID_INDEX", "bajaj-test-1")
            namespace = os.getenv("PINECONE_NAMESPACE", "bajaj-namespace")
            pc = Pinecone(api_key=api_key)
            RetrieverAgent._index = pc.Index(index_name)
            RetrieverAgent._namespace = namespace
            RetrieverAgent._pinecone_initialized = True

    def _compose_search_query(self, enhanced_query: EnhancedQuery) -> str:
        parts = [enhanced_query.raw_query] + enhanced_query.entities
        if enhanced_query.keywords:
            parts.extend(enhanced_query.keywords)
        if enhanced_query.conditions:
            parts.extend(enhanced_query.conditions)
        return " ".join(filter(None, parts))

    def retrieve_and_rerank(self, enhanced_query: EnhancedQuery, top_k_initial: int = 35, top_k_final: int = 5, alpha: float = 0.5) -> List[Dict[str, Any]]:
        search_query = self._compose_search_query(enhanced_query)
        result = RetrieverAgent._embedder.encode([search_query], return_dense=True, return_sparse=True)
        dense_emb = result['dense_vecs'][0]
        lw = result['lexical_weights'][0]
        indices = [int(idx) for idx, val in lw.items() if float(val) != 0.0]
        values = [float(val) for idx, val in lw.items() if float(val) != 0.0]
        sparse = {'indices': indices, 'values': values}
        # Apply alpha weighting if desired
        hdense, hsparse = hybrid_score_norm(dense_emb, sparse, alpha)
        try:
            results = RetrieverAgent._index.query(
                vector=hdense,
                sparse_vector=hsparse,
                top_k=top_k_final,
                namespace=RetrieverAgent._namespace,
                include_metadata=True
            )["matches"]
        except Exception as e:
            print(f"Error querying Pinecone: {e}")
            return []
        if not results:
            return []
        seen_ids = set()
        unique_results = []
        for res in results:
            chunk_id = res.get("id")
            if chunk_id not in seen_ids:
                unique_results.append(res)
                seen_ids.add(chunk_id)
        # Return results with Pinecone scores instead of reranking scores
        final_results = []
        for res in unique_results:
            final_results.append({
                "score": float(res.get("score", 0.0)),  # Use Pinecone's original score
                "metadata": res["metadata"]
            })
        
        return final_results