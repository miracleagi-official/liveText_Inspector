"""
alignment.py - JiWER 기반 정렬 및 메트릭 처리 모듈
"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple
import jiwer


class AlignType(Enum):
    HIT = "hit"           # 정확히 일치
    SUB = "sub"           # 오인식 (Substitution)
    DEL = "del"           # 누락 (Deletion) - 중간에 빠진 것
    INS = "ins"           # 추가됨 (Insertion)
    PENDING = "pending"   # 아직 말하지 않은 부분


@dataclass 
class AlignedToken:
    """정렬된 토큰 정보"""
    text: str
    align_type: AlignType
    
    
@dataclass
class PartialMetrics:
    """부분 평가 메트릭 (Trailing Deletion 제외)"""
    wer: float
    cer: float
    hits: int
    substitutions: int
    deletions: int
    insertions: int
    ref_processed: int  # 처리된 reference 토큰 수


def compute_alignment(reference: str, hypothesis: str) -> Tuple[List[AlignedToken], PartialMetrics]:
    """
    Reference와 Hypothesis 텍스트를 정렬하고 메트릭을 계산합니다.
    
    Args:
        reference: Ground Truth 텍스트
        hypothesis: STT 인식 결과 텍스트
        
    Returns:
        (정렬된 토큰 리스트, 부분 메트릭)
    """
    if not reference:
        return [], PartialMetrics(0.0, 0.0, 0, 0, 0, 0, 0)
    
    if not hypothesis:
        # hypothesis가 없으면 모든 reference가 pending
        ref_tokens = reference.split()
        aligned = [AlignedToken(t, AlignType.PENDING) for t in ref_tokens]
        return aligned, PartialMetrics(0.0, 0.0, 0, 0, 0, 0, 0)
    
    # JiWER로 정렬 수행
    output = jiwer.process_words(reference, hypothesis)
    
    ref_tokens = output.references[0]  # 토큰 리스트
    hyp_tokens = output.hypotheses[0]  # 토큰 리스트
    alignment = output.alignments[0]   # AlignmentChunk 리스트
    
    # 마지막으로 유의미한 매칭이 일어난 위치 찾기 (Trailing Deletion 판별용)
    last_non_delete_chunk_idx = -1
    for idx, chunk in enumerate(alignment):
        if chunk.type != 'delete':
            last_non_delete_chunk_idx = idx
    
    # 정렬 결과 생성
    aligned_tokens: List[AlignedToken] = []
    
    # 메트릭 카운터 (Trailing Deletion 제외)
    p_hit, p_sub, p_del, p_ins = 0, 0, 0, 0
    
    for chunk_idx, chunk in enumerate(alignment):
        is_trailing = chunk_idx > last_non_delete_chunk_idx
        
        if chunk.type == 'equal':
            # Hit: ref_start_idx ~ ref_end_idx 범위의 토큰들
            for i in range(chunk.ref_start_idx, chunk.ref_end_idx):
                aligned_tokens.append(AlignedToken(ref_tokens[i], AlignType.HIT))
                if not is_trailing:
                    p_hit += 1
                    
        elif chunk.type == 'substitute':
            # Substitution: ref 토큰을 빨간색으로
            for i in range(chunk.ref_start_idx, chunk.ref_end_idx):
                aligned_tokens.append(AlignedToken(ref_tokens[i], AlignType.SUB))
                if not is_trailing:
                    p_sub += 1
                    
        elif chunk.type == 'delete':
            # Deletion: 중간 누락 vs 아직 안 읽은 부분
            for i in range(chunk.ref_start_idx, chunk.ref_end_idx):
                if is_trailing:
                    aligned_tokens.append(AlignedToken(ref_tokens[i], AlignType.PENDING))
                else:
                    aligned_tokens.append(AlignedToken(ref_tokens[i], AlignType.DEL))
                    p_del += 1
                    
        elif chunk.type == 'insert':
            # Insertion: hypothesis에만 있는 토큰
            for i in range(chunk.hyp_start_idx, chunk.hyp_end_idx):
                aligned_tokens.append(AlignedToken(hyp_tokens[i], AlignType.INS))
                if not is_trailing:
                    p_ins += 1
    
    # Partial WER 계산 (Trailing 제외)
    ref_processed = p_hit + p_sub + p_del
    if ref_processed > 0:
        wer = (p_sub + p_del + p_ins) / ref_processed
    else:
        wer = 0.0
    
    # Partial CER (Trailing Deletion 제외)
    ref_cut = 0
    hyp_cut = 0

    for chunk_idx, chunk in enumerate(alignment):
        if chunk_idx > last_non_delete_chunk_idx:
            break

        # chunk마다 ref/hyp 인덱스가 있는 타입만 반영
        if chunk.type in ("equal", "substitute", "delete"):
            ref_cut = max(ref_cut, chunk.ref_end_idx)
        if chunk.type in ("equal", "substitute", "insert"):
            hyp_cut = max(hyp_cut, chunk.hyp_end_idx)

    partial_ref = " ".join(ref_tokens[:ref_cut]).strip()
    partial_hyp = " ".join(hyp_tokens[:hyp_cut]).strip()

    try:
        cer = jiwer.cer(partial_ref, partial_hyp) if partial_ref else 0.0
    except:
        cer = 0.0
    
    metrics = PartialMetrics(
        wer=wer,
        cer=cer,
        hits=p_hit,
        substitutions=p_sub,
        deletions=p_del,
        insertions=p_ins,
        ref_processed=ref_processed
    )
    
    return aligned_tokens, metrics


if __name__ == "__main__":
    # 간단한 테스트 케이스
    ref = "지난해 극장을 찾은 연간 관객 수가 역대 최다치를 기록했습니다. 전년보다 수치가 감소했을 거라는 추측이 많았는데 한국 영화들의 뒷심이 뜻밖의 결과로 이어졌습니다."
    hyp = "지난해 극장을 찾은 연간 관객 수가 역대 최다치를 기록했습니다." 
    
    aligned, metrics = compute_alignment(ref, hyp)
    
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    
    print("\nMetrics:")
    print(f"WER: {metrics.wer:.2f}, CER: {metrics.cer:.2f}")
    print(f"Hits: {metrics.hits}, Subs: {metrics.substitutions}, Dels: {metrics.deletions}, Ins: {metrics.insertions}")