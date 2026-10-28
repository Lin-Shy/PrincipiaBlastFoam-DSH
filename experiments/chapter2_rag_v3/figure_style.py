"""唯一中文论文结果图样式；规范见正式项目 release/protocol/figure_style.md。"""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

NAMES=dict(graph='完整来源图',bm25='BM25',e5='E5',bge_m3='BGE-M3',bm25_e5='BM25+E5',bm25_bge_m3='BM25+BGE-M3',bm25_parent='BM25父上下文',basic='基础搜索',direct='直接回答',no_cross='去来源关联',no_aliases='去中文别名',no_traversal='关闭关系遍历',anchor_only='仅交付锚点')
MAIN=list(NAMES)[:9]
COLORS=dict(zip(NAMES,['#b40426','#3b4cc0','#6f92f3','#5977e3','#9abbff','#d7dce3','#efcfbf','#f7ac8e','#e7745b','#4961d2','#7597f6','#f4987a','#d24b40']))
CMAP='coolwarm'
HEATMAP_NUM_SIZE=8
HEATMAP_AXIS_SIZE=8

def setup():
    installed={f.name for f in font_manager.fontManager.ttflist}
    candidates=['Microsoft YaHei','Noto Sans CJK SC','Source Han Sans SC','SimHei','SimSun']
    font=next((x for x in candidates if x in installed),None)
    if font is None:raise RuntimeError('缺少支持中文的字体，停止出图')
    plt.rcParams.update({'font.family':font,'font.size':9,'axes.titlesize':10,'axes.labelsize':9,'xtick.labelsize':8,'ytick.labelsize':8,'legend.fontsize':8,'axes.unicode_minus':False,'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'path','axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,'lines.linewidth':1.3,'lines.markersize':4,'legend.frameon':False,'figure.facecolor':'white','savefig.facecolor':'white'})
    return font

def save(fig,folder,name):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    fig.tight_layout()
    for ext in ['pdf','svg','png']:fig.savefig(folder/(name+'.'+ext),dpi=300,bbox_inches='tight')
    plt.close(fig)
