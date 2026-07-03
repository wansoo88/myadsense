"""analytics — 자체 사이트 방문 분석(서버사이드 nginx 로그).

parser.py  : nginx 로그(JSON 전용 + 공용 combined 백필) → 정규화·분류(자기/봇/사람) 방문 레코드
builder.py : 집계 + SQLite 일자 롤업 영속화 + 관리자 대시보드(index.html)·data.json 생성

클라이언트 JS 비콘 없음 → Core Web Vitals 영향 0. 읽기 전용(트래픽/클릭 생성과 무관, F3 리스크 0).
"""
