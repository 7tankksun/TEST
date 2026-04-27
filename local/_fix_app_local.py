from pathlib import Path
import re

path = Path(r"C:\code\SynologyDrive\local\app.py")
text = path.read_text(encoding="utf-8")

pattern = re.compile(r"CANDIDATES\s*=\s*\{[\s\S]*?\n\}\n\ndef run_analysis_task\(\):", re.MULTILINE)
match = pattern.search(text)
if not match:
    raise SystemExit("CANDIDATES block regex not found")

replacement = "from candidates_data import CANDIDATES\n\n\ndef run_analysis_task():"
text = text[:match.start()] + replacement + text[match.end():]

text = text.replace("# --- [도커 최적화 경로 설정] ---", "# --- [로컬 실행 경로 설정] ---")
text = text.replace("# 컨테이너 내부의 절대 경로를 기준으로 잡습니다.\n", "")
text = text.replace("# --- [도커용 한글 폰트 설정] ---", "# --- [로컬용 한글 폰트 설정] ---")
text = text.replace("print(f\"도커 환경: {font_path} 폰트 로드 완료\")", "print(f\"로컬 환경: {font_path} 폰트 로드 완료\")")
text = text.replace("# 파일이 없을 경우 리눅스 시스템 폰트 시도", "# 윈도우 기본 한글 폰트 우선, 없으면 나눔고딕 시도")
text = text.replace("plt.rcParams['font.family'] = 'NanumGothic'", "plt.rcParams['font.family'] = ['Malgun Gothic', 'NanumGothic', 'AppleGothic', 'sans-serif']")
text = text.replace("print(\"경고: fonts/NanumGothic.ttf 파일이 없습니다. 시스템 폰트를 사용합니다.\")", "print(\"안내: fonts/NanumGothic.ttf 파일이 없어 시스템 폰트를 사용합니다.\")")
text = text.replace("app.run(debug=True)", "app.run(host=\"127.0.0.1\", debug=False, use_reloader=False)")

path.write_text(text, encoding="utf-8")
print("app.py updated")
