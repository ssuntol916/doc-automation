"""Create new, explicit synthetic planning diagrams; no source images are edited."""
import argparse
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
import json
import math
from xml.sax.saxutils import escape

import pymupdf

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / 'outputs/manufact-ai-interim/assets'
CONTENT = PROJECT / 'examples/manufact-ai-interim/content.json'
W = 1800
NAVY = "#17324D"
TEAL = "#197D87"
INK = "#243A4E"
MUTED = "#526579"
PALE = "#F1F7FA"
NOTICE = "합성 계획도 · 실제 구축/실행 증거 아님"


class Diagram:
    def __init__(self, title, subtitle, height=1000):
        self.height = height
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}">',
                      '<defs><marker id="arrow" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="12" markerHeight="12" orient="auto-start-reverse"><path d="M 0 1 L 11 6 L 0 11 z" fill="#197D87"/></marker></defs>',
                      f'<rect width="{W}" height="{height}" fill="#FFFFFF"/>',
                      '<rect x="60" y="55" width="12" height="76" rx="4" fill="#197D87"/>']
        self.labels = []
        self.text(100, 108, title, 56, NAVY, bold=True)
        self.text(100, 172, subtitle, 36, MUTED)
        self.parts.append(f'<line x1="60" y1="{height-145}" x2="1740" y2="{height-145}" stroke="#C5D5DD" stroke-width="2"/>')
        self.text(72, height-80, NOTICE, 42, TEAL, bold=True)

    def text(self, x, y, text, size=42, colour=INK, bold=False, anchor="start"):
        weight = "700" if bold else "400"
        lines = text.split("\n")
        for i, line in enumerate(lines):
            yy = y+i*size*1.28
            self.parts.append(f'<text x="{x}" y="{yy}" font-family="sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="{colour}">{escape(line)}</text>')
            self.labels.append(line)

    def box(self, x, y, w, h, title, *, note=None, fill=PALE, size=44):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{fill}" stroke="#628B9D" stroke-width="3"/>')
        lines = title.split("\n")
        start = y+h/2-(len(lines)-1)*size*0.64+size*0.33
        if note:
            start -= 25
        self.text(x+w/2, start, title, size, NAVY, bold=True, anchor="middle")
        if note:
            self.text(x+w/2, y+h-33, note, 35, MUTED, anchor="middle")

    def arrow(self, points, *, dashed=False, label=None, label_xy=None):
        joined = " ".join(f"{x},{y}" for x,y in points)
        dash = ' stroke-dasharray="14 10"' if dashed else ""
        self.parts.append(f'<polyline points="{joined}" fill="none" stroke="{TEAL}" stroke-width="5" stroke-linejoin="round" marker-end="url(#arrow)"{dash}/>')
        # MuPDF does not display SVG markers consistently; materialize the head.
        x,y=points[-1];px,py=points[-2]
        length=math.hypot(x-px,y-py);ux,uy=(x-px)/length,(y-py)/length
        bx,by=x-22*ux,y-22*uy
        triangle=f"{x},{y} {bx-12*uy},{by+12*ux} {bx+12*uy},{by-12*ux}"
        self.parts.append(f'<polygon points="{triangle}" fill="{TEAL}"/>')
        if label:
            self.text(*label_xy, label, 34, TEAL)

    def note(self, text, y, *, colour=MUTED):
        self.text(72, y, text, 38, colour)

    def save(self, stem, purpose):
        svg = ROOT/(stem+".svg")
        png = ROOT/(stem+".png")
        if svg.exists() or png.exists():
            raise RuntimeError("Refusing to overwrite diagram: "+stem)
        payload = "\n".join([*self.parts,"</svg>"])
        svg.write_text(payload, encoding="utf-8")
        with pymupdf.open(stream=svg.read_bytes(),filetype="svg") as doc:
            page = doc[0]
            raw = page.get_text("dict")
            spans = [s for b in raw["blocks"] if "lines" in b for l in b["lines"] for s in l["spans"]]
            for span in spans:
                x0,y0,x1,y1=span["bbox"]
                if min(x0,y0)<-1 or x1>W+1 or y1>self.height+1:
                    raise ValueError("Rendered text exceeds canvas: "+repr(span["text"]))
            page.get_pixmap(matrix=pymupdf.Matrix(1,1),alpha=False).save(png)
            fonts = sorted({s["font"] for s in spans})
        return {"id":stem,"purpose":purpose,"svg":{"path":str(svg),"sha256":sha256(svg.read_bytes()).hexdigest()},
                "png":{"path":str(png),"sha256":sha256(png.read_bytes()).hexdigest()},"width_px":W,"height_px":self.height,
                "labels":self.labels,"actual_rendered_font_names":fonts,"is_synthetic_plan":True,
                "actual_execution_evidence":False,"source_image_edited":False,"visual_review_status":"pending"}


def main():
    global ROOT, CONTENT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New local asset directory')
    parser.add_argument('--content', type=Path, default=CONTENT)
    args = parser.parse_args()
    ROOT = args.output.expanduser().resolve()
    if not ROOT.is_relative_to(PROJECT / "outputs"):
        parser.error("Asset output must be inside this checkout's ignored outputs/ directory")
    CONTENT = args.content.expanduser().resolve()
    ROOT.mkdir(parents=True,exist_ok=True)
    result=[]
    d=Diagram("현행 공정 흐름 — 가정", "가상정밀제조(합성) · 사출성형 부품 외관검사",820)
    for x,label in zip([60,480,900,1320],["사출성형","작업자\n외관 확인","수기 기록","LOT별 집계\n지연 가능"]):
        d.box(x,260,360,180,label)
    for x in [420,840,1260]:d.arrow([(x,350),(x+50,350)])
    d.note("가정한 문제: 판정 기준의 편차, 이미지와 LOT 이력의 분리",540)
    d.note("현장 조사·측정 자료가 없으므로 현재 사업장의 실제 상태를 뜻하지 않음",598)
    result.append(d.save("01_process_as_is","Assumed current-state process, not an observed site"))

    d=Diagram("목표 공정 흐름 — 합성 계획", "AI 보조 판정과 작업자 확인을 LOT 이력에 연결",1040)
    boxes=[(60,245,"1  사출성형"),(650,245,"2  트리거·촬영"),(1240,245,"3  엣지 AI\n추론"),
           (1240,540,"4  작업자\n재확인"),(650,540,"5  MES 전송\nLOT·이미지·판정"),(60,540,"6  KPI\n대시보드")]
    for x,y,label in boxes:d.box(x,y,500,180,label)
    d.arrow([(560,335),(635,335)]);d.arrow([(1150,335),(1225,335)])
    d.arrow([(1490,425),(1490,520)])
    d.arrow([(1240,630),(1165,630)]);d.arrow([(650,630),(575,630)])
    d.note("AI 불확실·통신 오류 시 자동 확정 대신 작업자 확인 경로로 전환할 계획",820)
    result.append(d.save("02_process_to_be","Planned target process and human confirmation path"))

    d=Diagram("AI 통합시스템 구성 — 합성 계획", "촬영·추론·판정 이력·업무시스템 연동의 논리적 연결",1130)
    for x,label in zip([60,480,900,1320],["카메라·조명","엣지 PC\nAI 추론","검사 API","이벤트 저장\nLOT·판정·버전"]):d.box(x,255,360,180,label,size=42)
    for x in [420,840,1260]:d.arrow([(x,345),(x+50,345)])
    d.box(60,630,700,180,"학습 서버\n승인된 버전만 배포할 계획",size=43)
    d.arrow([(760,720),(900,720),(900,525),(660,525),(660,450)],dashed=True)
    d.text(70,585,"배포 규칙의 제안 · 실제 승인 미확인",34,TEAL)
    d.box(1030,630,650,180,"MES 연동·대시보드\n이력 조회·KPI 집계",size=44)
    d.arrow([(1500,435),(1500,610)])
    d.note("모델 버전·LOT·촬영 시각·판정 근거를 연결할 계획이며 실제 저장 결과는 미확인",925)
    result.append(d.save("03_ai_architecture","Logical AI system and controlled model deployment plan"))

    d=Diagram("하드웨어·네트워크 연결 — 합성 계획", "설비 제어와 AI 판정 경로를 분리하고 오류 시 작업자 확인",1090)
    d.box(60,245,430,170,"카메라·조명")
    d.box(60,550,430,170,"PLC·트리거\n연계 협의 대상")
    d.box(680,390,430,190,"엣지 PC\nAI 보조 판정")
    d.box(1310,245,430,170,"업무 스위치\n검사망")
    d.box(1310,550,430,170,"방화벽·MES\n허용 API 연계")
    d.arrow([(490,330),(580,330),(580,440),(665,440)])
    # The connection scope is unresolved, so no directional control link is drawn.
    d.parts.append('<line x1="490" y1="635" x2="600" y2="635" stroke="#8797A4" stroke-width="3"/>')
    d.text(620,650,"범위 미확정",32,MUTED)
    d.arrow([(1110,485),(1210,485),(1210,330),(1295,330)])
    d.arrow([(1525,415),(1525,530)])
    d.note("PLC 접속·직접 제어는 범위 미확정 · 현장·설비 공급사와 협의 필요",840)
    d.note("접속·설치·통신 성능은 실제 시험 후 별도 확인",895)
    result.append(d.save("04_hw_network","Planned hardware network and safety boundary"))

    d=Diagram("주요 장비 설치 영역 — 합성 계획", "개념적 배치도 · 현장 도면·치수·실제 설치사진이 아님",1090)
    d.parts.append('<rect x="60" y="235" width="1680" height="560" rx="14" fill="#FBFCFD" stroke="#94A9B5" stroke-width="3" stroke-dasharray="14 9"/>')
    d.text(95,292,"생산·검사 영역(가정)",38,TEAL,bold=True)
    d.box(100,360,420,220,"사출성형 설비\n트리거 지점")
    d.box(690,360,420,220,"검사 위치\n카메라·조명")
    d.box(1280,360,420,220,"작업자 확인\n엣지 PC·화면")
    d.arrow([(520,470),(670,470)]);d.arrow([(1110,470),(1260,470)])
    d.text(100,695,"배선·조명 차광·안전거리·보행 동선은 현장 협의 후 확정",40,MUTED)
    d.note("현장 배치·전원·네트워크·안전 표지의 적합성은 아직 확인하지 않음",900)
    result.append(d.save("05_installation_plan","Abstract equipment placement, not an actual site map"))

    d=Diagram("SW·데이터·모델 검증 절차 — 합성 계획", "LOT 단위 데이터 분리로 학습·검증 간 정보 누출을 방지할 계획",1090)
    boxes=[(60,245,"1  LOT별\n데이터 분리"),(650,245,"2  라벨 검수\n불량 기준 합의"),(1240,245,"3  후보 모델\n선정 계획"),
           (1240,550,"4  독립 검증\n지표·로그 확인"),(650,550,"5  승인 대기\n검토 근거 확보"),(60,550,"6  배포 계획\n버전·복귀 관리")]
    for x,y,label in boxes:d.box(x,y,500,180,label,size=43)
    d.arrow([(560,335),(635,335)]);d.arrow([(1150,335),(1225,335)])
    d.arrow([(1490,425),(1490,530)])
    d.arrow([(1240,640),(1165,640)]);d.arrow([(650,640),(575,640)])
    d.note("검증 계획: 미검출·오검출·판정 지연을 분리 측정하고 원시 기록을 보존",870)
    d.note("실행 여부·검증 수치·승인 결과는 자료 미제공으로 모두 미확인",925)
    result.append(d.save("06_sw_data_pipeline","Planned data separation, model validation and controlled deployment"))

    d=Diagram("AI 성능 검증 자료", "현재 문서에는 목표와 검증방법만 기술",780)
    d.parts.append('<rect x="100" y="245" width="1600" height="265" rx="18" fill="#F2F6F8" stroke="#628B9D" stroke-width="3"/>')
    d.text(900,325,"실측자료 미제공",60,NAVY,bold=True,anchor="middle")
    d.text(900,405,"성능 그래프·혼동행렬·지연시간 원시로그는",42,MUTED,anchor="middle")
    d.text(900,470,"검증 수행 후 첨부",46,TEAL,bold=True,anchor="middle")
    d.note("측정값·성공 판정·완료 실적을 대신하는 예시 그래프를 생성하지 않음",570)
    result.append(d.save("07_measurement_pending","Explicit placeholder for missing actual measurement evidence"))

    result.append(sw_modules())

    manifest={"schema_version":"synthetic-planning-assets-1","recorded_at":datetime.now(timezone.utc).isoformat(),
              "creator":"manufact_ai_interim_diagrams","renderer":{"name":"PyMuPDF SVG renderer","version":pymupdf.VersionBind},
              "font_availability_checked":{"local_hangul_font":"/System/Library/Fonts/AppleSDGothicNeo.ttc","exists":Path('/System/Library/Fonts/AppleSDGothicNeo.ttc').is_file()},
              "font_note":"SVG sans-serif is rendered by MuPDF using Helvetica and its embedded Droid Sans Fallback for Hangul; local Apple font identity is not claimed.",
              "scope":"New vector planning diagrams from explicitly synthetic project assumptions. No existing source picture is edited; no site photograph, execution result, approval or measurement evidence is created.",
              "assets":result}
    with (ROOT/'manifest.json').open('x') as f:f.write(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({"assets":len(result),"root":str(ROOT),"png_dimensions":[(x['id'],x['width_px'],x['height_px']) for x in result]},ensure_ascii=False))


def sw_modules():
    """Map the twelve supplied synthetic functions to services without results."""
    source=CONTENT
    content=json.loads(source.read_text())
    functions={f['id']:f for f in content['functions']}
    groups=[
        (60,230,'기준정보',['SYN-F01']),
        (650,230,'영상·라벨 관리',['SYN-F02','SYN-F03','SYN-F04']),
        (1240,230,'현장 AI·예외 처리',['SYN-F05','SYN-F12']),
        (60,460,'작업자 품질확인',['SYN-F06']),
        (650,460,'LOT 검사이력',['SYN-F07']),
        (1240,460,'KPI 대시보드',['SYN-F08']),
        (60,720,'모델 버전관리',['SYN-F09']),
        (650,720,'MES 연계',['SYN-F10']),
        (1240,720,'권한·감사',['SYN-F11']),
    ]
    assert set(functions)=={ident for *_,ids in groups for ident in ids}
    assert all(f['actual_status'] is None for f in functions.values())
    d=Diagram('SW 모듈 구성과 데이터 흐름 — 합성 계획','12개 합성 기능을 9개 서비스로 구성 · 품목·LOT·검사 ID로 연결',1100)
    for x,y,title,ids in groups:
        d.parts.append(f'<rect x="{x}" y="{y}" width="500" height="185" rx="18" fill="{PALE}" stroke="#628B9D" stroke-width="3"/>')
        d.text(x+250,y+48,title,40,NAVY,bold=True,anchor='middle')
        for i,ident in enumerate(ids):
            d.text(x+25,y+94+i*38,ident+'  '+functions[ident]['name'],32,INK)
    d.arrow([(560,322),(635,322)])
    d.arrow([(1150,322),(1225,322)])
    d.arrow([(1490,415),(1490,437),(310,437),(310,445)])
    d.arrow([(560,552),(635,552)])
    d.arrow([(1150,552),(1225,552)])
    d.arrow([(900,645),(900,705)])
    d.text(72,690,'공통 운영 서비스(계획)',34,TEAL,bold=True)
    d.text(72,945,'전 기능의 구현·시험·운영 상태는 미확인 · 모델 승인과 연계 규격은 확인 후 확정',31,MUTED)
    item=d.save('08_sw_modules','Nine logical services and data flow covering all twelve synthetic functions')
    item['content_source']={'path':str(source),'sha256':sha256(source.read_bytes()).hexdigest()}
    item['function_ids']=list(functions)
    item['service_groups']=[{'service':title,'function_ids':ids} for _,_,title,ids in groups]
    return item


if __name__=="__main__":main()
