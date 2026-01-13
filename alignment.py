"""
alignment.py - JiWER 기반 정렬 및 메트릭 처리 모듈 (관대한 비교 버전)
"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple
import re
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


# ============ 한국어 숫자 변환 ============

# 기본 숫자
KO_DIGITS = {
    '영': 0, '공': 0, '빵': 0,
    '일': 1, '하나': 1, '한': 1,
    '이': 2, '둘': 2, '두': 2,
    '삼': 3, '셋': 3, '세': 3,
    '사': 4, '넷': 4, '네': 4,
    '오': 5, '다섯': 5,
    '육': 6, '여섯': 6,
    '칠': 7, '일곱': 7,
    '팔': 8, '여덟': 8,
    '구': 9, '아홉': 9,
}

# 단위
KO_UNITS = {
    '십': 10,
    '백': 100,
    '천': 1000,
    '만': 10000,
    '억': 100000000,
    '조': 1000000000000,
}

def korean_to_number(text: str) -> str:
    """
    한국어 숫자를 아라비아 숫자로 변환
    예: '천구백오십이' -> '1952', '삼십오' -> '35'
    변환 실패 시 원본 반환
    """
    if not text:
        return text
    
    # 이미 아라비아 숫자면 그대로 반환
    if text.isdigit():
        return text
    
    # 한국어 숫자가 포함되어 있는지 확인
    has_korean_num = any(c in text for c in list(KO_DIGITS.keys()) + list(KO_UNITS.keys()))
    if not has_korean_num:
        return text
    
    try:
        result = 0
        current = 0
        temp = 0
        
        i = 0
        while i < len(text):
            matched = False
            
            # 긴 단어부터 매칭 시도 (하나, 둘, 셋 등)
            for length in [2, 1]:
                if i + length <= len(text):
                    chunk = text[i:i+length]
                    
                    if chunk in KO_DIGITS:
                        temp = KO_DIGITS[chunk]
                        i += length
                        matched = True
                        break
                    elif chunk in KO_UNITS:
                        unit = KO_UNITS[chunk]
                        if temp == 0:
                            temp = 1
                        
                        if unit >= 10000:  # 만, 억, 조
                            current = (current + temp) * unit
                            temp = 0
                        else:  # 십, 백, 천
                            current += temp * unit
                            temp = 0
                        i += length
                        matched = True
                        break
            
            if not matched:
                # 한국어 숫자가 아닌 문자가 있으면 원본 반환
                return text
        
        result = current + temp
        return str(result) if result > 0 else text
        
    except:
        return text


def normalize_numbers(text: str) -> str:
    """
    텍스트 내 한국어 숫자를 아라비아 숫자로 변환
    """
    # 한국어 숫자 패턴 찾기 (연속된 한국어 숫자 단어)
    ko_num_chars = ''.join(list(KO_DIGITS.keys()) + list(KO_UNITS.keys()))
    pattern = f'[{re.escape(ko_num_chars)}]+'
    
    def replace_korean_num(match):
        return korean_to_number(match.group())
    
    return re.sub(pattern, replace_korean_num, text)


def normalize_text(text: str) -> str:
    """
    텍스트 정규화: 문장부호 제거, 공백 정리, 숫자 통일
    (단어 구분용 - 공백 유지)
    """
    # 한국어 숫자를 아라비아 숫자로 변환
    text = normalize_numbers(text)
    # 문장 부호 제거 (한글, 영문, 숫자만 유지)
    text = re.sub(r'[.,?!;:"\'\-…·\(\)\[\]「」『』《》<>]', '', text)
    # 연속 공백을 하나로
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def normalize_text_no_space(text: str) -> str:
    """
    텍스트 정규화: 문장부호 및 공백 모두 제거
    (비교용 - 띄어쓰기 무시)
    """
    # 한국어 숫자를 아라비아 숫자로 변환
    text = normalize_numbers(text)
    # 문장 부호 및 공백 모두 제거
    text = re.sub(r'[.,?!;:"\'\-…·\(\)\[\]「」『』《》<>\s]', '', text)
    return text


def levenshtein_distance(s1: str, s2: str) -> int:
    """레벤슈타인 거리 계산"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    
    return prev_row[-1]


def is_similar(ref_token: str, hyp_token: str, threshold: float = 0.6) -> bool:
    """
    두 토큰이 유사한지 판단
    - 문장부호 및 공백 제거 후 비교
    - 레벤슈타인 거리 기반 유사도 체크
    
    Args:
        ref_token: 대본 토큰
        hyp_token: STT 인식 토큰
        threshold: 유사도 임계값 (0~1, 높을수록 엄격)
    """
    # 공백까지 제거한 정규화
    ref_norm = normalize_text_no_space(ref_token)
    hyp_norm = normalize_text_no_space(hyp_token)
    
    # 빈 문자열 처리
    if not ref_norm and not hyp_norm:
        return True
    if not ref_norm or not hyp_norm:
        return False
    
    # 완전 일치
    if ref_norm == hyp_norm:
        return True
    
    # 레벤슈타인 거리 기반 유사도
    max_len = max(len(ref_norm), len(hyp_norm))
    distance = levenshtein_distance(ref_norm, hyp_norm)
    similarity = 1 - (distance / max_len)
    
    return similarity >= threshold


class LenientWordTransform(jiwer.AbstractTransform):
    """
    관대한 단어 비교를 위한 JiWER Transform
    - 문장부호 제거
    - 유사 단어 동일 처리
    """
    def __init__(self, similarity_threshold: float = 0.6):
        self.threshold = similarity_threshold
        self._mapping = {}  # hyp -> ref 매핑 캐시
        
    def process_string(self, s: str) -> str:
        return normalize_text(s)
    
    def process_list(self, tokens: List[str]) -> List[str]:
        return [normalize_text(t) for t in tokens if normalize_text(t)]


def compute_alignment(reference: str, hypothesis: str, similarity_threshold: float = 0.6) -> Tuple[List[AlignedToken], PartialMetrics]:
    """
    Reference와 Hypothesis 텍스트를 정렬하고 메트릭을 계산합니다.
    순차적 매칭: 앞에서부터 순서대로 비교, 제한된 lookahead만 사용
    
    Args:
        reference: Ground Truth 텍스트
        hypothesis: STT 인식 결과 텍스트
        similarity_threshold: 유사도 임계값 (0.6 = 60% 이상 유사하면 일치)
        
    Returns:
        (정렬된 토큰 리스트, 부분 메트릭)
    """
    if not reference:
        return [], PartialMetrics(0.0, 0.0, 0, 0, 0, 0, 0)
    
    # 원본 토큰 (표시용)
    ref_tokens_orig = reference.split()
    
    if not hypothesis:
        # hypothesis가 없으면 모든 reference가 pending
        aligned = [AlignedToken(t, AlignType.PENDING) for t in ref_tokens_orig]
        return aligned, PartialMetrics(0.0, 0.0, 0, 0, 0, 0, 0)
    
    # 공백 제거된 전체 문자열 (비교용)
    ref_no_space = normalize_text_no_space(reference)
    hyp_no_space = normalize_text_no_space(hypothesis)
    
    if not ref_no_space:
        return [], PartialMetrics(0.0, 0.0, 0, 0, 0, 0, 0)
    
    if not hyp_no_space:
        aligned = [AlignedToken(t, AlignType.PENDING) for t in ref_tokens_orig]
        return aligned, PartialMetrics(0.0, 0.0, 0, 0, 0, 0, 0)
    
    # 순차적 문자 매칭 (제한된 lookahead)
    char_states, last_ref_idx = sequential_char_align(ref_no_space, hyp_no_space, max_lookahead=3)
    
    # 각 원본 토큰이 차지하는 문자 범위 계산
    token_char_ranges = []
    char_idx = 0
    for token in ref_tokens_orig:
        token_normalized = normalize_text_no_space(token)
        if token_normalized:
            start = char_idx
            end = char_idx + len(token_normalized)
            token_char_ranges.append((start, end, token))
            char_idx = end
        else:
            # 정규화 후 빈 토큰 (문장부호만 있는 경우)
            token_char_ranges.append((char_idx, char_idx, token))
    
    # 토큰별 상태 결정
    aligned_tokens: List[AlignedToken] = []
    total_hits = 0
    total_subs = 0
    total_dels = 0
    
    for start, end, token in token_char_ranges:
        if start == end:
            # 빈 토큰 (문장부호만) -> HIT로 처리
            aligned_tokens.append(AlignedToken(token, AlignType.HIT))
            continue
        
        # 해당 토큰의 문자들 상태 확인
        token_states = char_states[start:end]
        
        if not token_states:
            aligned_tokens.append(AlignedToken(token, AlignType.PENDING))
            continue
        
        # 토큰이 아직 처리되지 않은 부분인지 확인
        if start > last_ref_idx:
            aligned_tokens.append(AlignedToken(token, AlignType.PENDING))
            continue
        
        # 상태 카운트
        hits = token_states.count('hit')
        subs = token_states.count('sub')
        dels = token_states.count('del')
        pendings = token_states.count('pending')
        
        # 일부만 처리된 경우 (토큰 중간에서 끊긴 경우)
        if pendings > 0 and pendings < len(token_states):
            # 처리된 부분 비율로 판단
            processed = hits + subs + dels
            if processed > 0:
                hit_ratio = hits / processed
                if hit_ratio >= similarity_threshold:
                    aligned_tokens.append(AlignedToken(token, AlignType.HIT))
                    total_hits += 1
                else:
                    aligned_tokens.append(AlignedToken(token, AlignType.SUB))
                    total_subs += 1
            else:
                aligned_tokens.append(AlignedToken(token, AlignType.PENDING))
            continue
        
        # 전부 pending이면
        if pendings == len(token_states):
            aligned_tokens.append(AlignedToken(token, AlignType.PENDING))
            continue
        
        token_len = hits + subs + dels
        hit_ratio = hits / token_len if token_len > 0 else 0
        
        # 60% 이상 hit이면 전체를 HIT로 처리
        if hit_ratio >= similarity_threshold:
            aligned_tokens.append(AlignedToken(token, AlignType.HIT))
            total_hits += 1
        elif hits + subs > dels:
            # substitution이 많으면 SUB
            aligned_tokens.append(AlignedToken(token, AlignType.SUB))
            total_subs += 1
        else:
            # deletion이 많으면 DEL
            aligned_tokens.append(AlignedToken(token, AlignType.DEL))
            total_dels += 1
    
    # 메트릭 계산
    ref_processed = total_hits + total_subs + total_dels
    if ref_processed > 0:
        wer = (total_subs + total_dels) / ref_processed
    else:
        wer = 0.0
    
    # CER 계산 (처리된 부분만)
    try:
        if last_ref_idx >= 0:
            partial_ref = ref_no_space[:last_ref_idx + 1]
            if partial_ref and hyp_no_space:
                cer = jiwer.cer(partial_ref, hyp_no_space)
            else:
                cer = 0.0
        else:
            cer = 0.0
    except:
        cer = 0.0
    
    metrics = PartialMetrics(
        wer=wer,
        cer=cer,
        hits=total_hits,
        substitutions=total_subs,
        deletions=total_dels,
        insertions=0,
        ref_processed=ref_processed
    )
    
    return aligned_tokens, metrics


def sequential_char_align(ref: str, hyp: str, max_lookahead: int = 3) -> Tuple[List[str], int]:
    """
    순차적 문자 매칭 (제한된 lookahead)
    
    앞에서부터 순서대로 비교하면서:
    - 일치하면 hit
    - 불일치 시 max_lookahead 범위 내에서만 탐색
    - 범위 내 못 찾으면 sub 처리
    
    Args:
        ref: 공백 제거된 reference 문자열
        hyp: 공백 제거된 hypothesis 문자열
        max_lookahead: 앞으로 탐색할 최대 문자 수
        
    Returns:
        (ref 길이만큼의 상태 리스트, 마지막으로 처리된 ref 인덱스)
    """
    ref_states = ['pending'] * len(ref)
    ref_idx = 0
    hyp_idx = 0
    
    while ref_idx < len(ref) and hyp_idx < len(hyp):
        # 현재 문자 비교
        if ref[ref_idx] == hyp[hyp_idx]:
            ref_states[ref_idx] = 'hit'
            ref_idx += 1
            hyp_idx += 1
            continue
        
        # 불일치 - lookahead로 탐색
        found = False
        
        # Case 1: ref에서 deletion 탐색 (hyp의 현재 문자가 ref의 앞쪽에 있는지)
        for look in range(1, max_lookahead + 1):
            if ref_idx + look < len(ref) and ref[ref_idx + look] == hyp[hyp_idx]:
                # ref_idx ~ ref_idx+look-1 은 DEL (누락)
                for i in range(ref_idx, ref_idx + look):
                    ref_states[i] = 'del'
                ref_idx += look
                # 매칭된 문자는 다음 루프에서 처리
                found = True
                break
        
        if found:
            continue
        
        # Case 2: hyp에서 insertion 탐색 (ref의 현재 문자가 hyp의 앞쪽에 있는지)
        for look in range(1, max_lookahead + 1):
            if hyp_idx + look < len(hyp) and hyp[hyp_idx + look] == ref[ref_idx]:
                # hyp_idx ~ hyp_idx+look-1 은 INS (삽입된 것, 무시)
                hyp_idx += look
                # 매칭된 문자는 다음 루프에서 처리
                found = True
                break
        
        if found:
            continue
        
        # Case 3: 둘 다 못 찾음 - substitution
        ref_states[ref_idx] = 'sub'
        ref_idx += 1
        hyp_idx += 1
    
    # 마지막으로 처리된 ref 인덱스 (hit, sub, del 중 하나인 마지막 위치)
    last_processed = -1
    for i in range(len(ref_states) - 1, -1, -1):
        if ref_states[i] != 'pending':
            last_processed = i
            break
    
    return ref_states, last_processed


if __name__ == "__main__":
    # 숫자 변환 테스트
    print("=== 숫자 변환 테스트 ===")
    test_nums = [
        "천구백오십이",
        "삼십오",
        "백이십삼",
        "이천이십오",
        "일억이천삼백만",
    ]
    for num in test_nums:
        print(f"{num} -> {korean_to_number(num)}")
    
    print("\n" + "="*50)
    
    # 테스트 케이스
    print("\n=== 테스트 1: 유사 발음 ===")
    ref = "지난해 극장을 찾은 연간 관객 수가 역대 최다치를 기록했습니다."
    hyp = "지난해 극장을 찾은 연간 관객 수가 역대 최다치를 기록햇습니다"  # 했습니다 -> 햇습니다
    
    aligned, metrics = compute_alignment(ref, hyp)
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    print(f"\nWER: {metrics.wer:.2%}, CER: {metrics.cer:.2%}")
    
    print("\n=== 테스트 2: 문장부호 차이 ===")
    ref = "안녕하세요? 반갑습니다!"
    hyp = "안녕하세요 반갑습니다"
    
    aligned, metrics = compute_alignment(ref, hyp)
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    print(f"\nWER: {metrics.wer:.2%}, CER: {metrics.cer:.2%}")
    
    print("\n=== 테스트 3: 지적 vs 지저 ===")
    ref = "선생님이 지적했습니다"
    hyp = "선생님이 지저했습니다"
    
    aligned, metrics = compute_alignment(ref, hyp)
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    print(f"\nWER: {metrics.wer:.2%}, CER: {metrics.cer:.2%}")
    
    print("\n=== 테스트 4: 한국어 숫자 vs 아라비아 숫자 ===")
    ref = "1952년에 태어났습니다"
    hyp = "천구백오십이년에 태어났습니다"
    
    aligned, metrics = compute_alignment(ref, hyp)
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    print(f"\nWER: {metrics.wer:.2%}, CER: {metrics.cer:.2%}")
    
    print("\n=== 테스트 5: 삼십오 vs 35 ===")
    ref = "나이가 35살입니다"
    hyp = "나이가 삼십오살입니다"
    
    aligned, metrics = compute_alignment(ref, hyp)
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    print(f"\nWER: {metrics.wer:.2%}, CER: {metrics.cer:.2%}")
    
    print("\n=== 테스트 6: 띄어쓰기 차이 (덴마크군도 vs 덴마크 군도) ===")
    ref = "덴마크군도 여행"
    hyp = "덴마크 군도 여행"
    
    aligned, metrics = compute_alignment(ref, hyp)
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    print(f"\nWER: {metrics.wer:.2%}, CER: {metrics.cer:.2%}")
    
    print("\n=== 테스트 7: 띄어쓰기 분리 입력 ===")
    ref = "대한민국 만세"
    hyp = "대한 민국 만세"  # 대한민국이 대한 민국으로 분리
    
    aligned, metrics = compute_alignment(ref, hyp)
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    print(f"\nWER: {metrics.wer:.2%}, CER: {metrics.cer:.2%}")
    
    print("\n=== 테스트 8: 부분 입력 (중간까지만) ===")
    ref = "오늘 날씨가 매우 좋습니다"
    hyp = "오늘 날씨가"  # 중간까지만 입력
    
    aligned, metrics = compute_alignment(ref, hyp)
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    print(f"\nWER: {metrics.wer:.2%}, CER: {metrics.cer:.2%}")
    
    print("\n=== 테스트 9: 순차 매칭 확인 (끝까지 탐색 방지) ===")
    ref = "가나다라 마바사 가나다라"  # '가나다라'가 앞뒤로 있음
    hyp = "가나다라 마바"  # 중간까지만
    
    aligned, metrics = compute_alignment(ref, hyp)
    for token in aligned:
        print(f"{token.text}: {token.align_type.value}")
    print(f"\nWER: {metrics.wer:.2%}, CER: {metrics.cer:.2%}")