"""engine.measure — 1차 측정 하네스 (AUTOMATION.md 🟢 수집·분석 계층).

우리가 직접 잰 값만 만든다: 네트워크 지연·다운로드, 컨테이너 이미지 크기·기동, 설치 파일 크기·버전,
데스크톱 앱 설치 용량·콜드 스타트·유휴 메모리(+스크린샷). 결과는 data/measurements/<suite>.<host>.json.
본문 주입은 scripts/add_measurements.py (빌드 전, 멱등). 근거: reports/adsense-승인연구-2026-09-06.html §5.
"""
