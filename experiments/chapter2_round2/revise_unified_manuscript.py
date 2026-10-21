"""Synchronize the manuscript with the user-approved unified comparison."""
from common import WORKSPACE

ROOT=WORKSPACE/'graduation-thesis-materials/graduation-manuscript'


def edit(name,old,new):
    path=ROOT/name;text=path.read_text(encoding='utf-8')
    if old not in text:raise ValueError('Missing manuscript anchor: '+name+' / '+old[:50])
    path.write_text(text.replace(old,new),encoding='utf-8')


def main():
    (ROOT/'docs/chap02_knowledge_qa_results.tex').write_text(r'''% !TeX root = ../main.tex
\section{实验结果与分析}
\label{sec:ch2-qa-results}

\subsection{九种方法的统一回答质量比较}

表\ref{tab:ch2-model-scales}统一比较来源图、BM25、E5 Dense、BGE-M3 Dense、两种词项与向量融合、BM25父上下文、基础搜索和模型直接作答，共九种方法。每个已运行模型、每行均以相同40道测试题为分母；未在8B运行的新增方法不填推测值。完整图与BM25各保留原运行和复验两行，使新增与既有基线能够在同一总表中阅读，同时保留真实执行身份。开发160题的统一结果列于附录。

\input{assets/chapter2/dev160_test40/overall.tex}

原运行中，完整图EAS为8B的32.3--38.1分、14B的62.0分；14B的BM25为45.2--51.0分。复验采用逐行去重的公共交付消费者，完整图为57.4--60.5分，BM25为51.5--53.2分。两次完整图和BM25结果均保留，不平均或选择其中一次作为全部方法的共同参照。两次运行的变化包含消费者和批次差异，不能解释为模型本身能力改变。

在14B上，E5 Dense为36.6分，BGE-M3 Dense为51.1分；BM25+E5为32.1--35.4分，BM25+BGE-M3为42.3--43.1分，BM25父上下文为44.2--48.0分。BGE结果高于本次E5原记录，但二者来自不同运行协议、编码长度与分段规则，不能将差值全部归因于Embedding替换。复验中BGE、融合和父上下文均未普遍超过同协议BM25，较强语义编码或层次恢复不自动保证更完整的回答。

完整有效率要求整题必要知识、事实与条件全部通过。完整图原运行在8B为12.5\%、14B为37.5\%，14B复验为25.0\%；BM25对应14B原运行为20.0--22.5\%、复验为22.5\%。较高EAS不等于相同比例的问题全部答对。未知形成的范围不是重复运行置信区间；模型规模比较亦包含工具采用与原批次差异。

\begin{figure}[htbp]
\centering
\includegraphics[width=\linewidth]{assets/chapter2/dev160_test40/fig2_model_scales.pdf}
\caption{全部实测主方法的40题测试质量。圆点为原运行，方点为复验；点为下界，线段延至裁判未知上界。没有运行的方法不绘点。}
\label{fig:ch2-model-quality}
\end{figure}
\FloatBarrier

\subsection{题型与知识组差异}

测试集四类分别7、6、20、7题，开发集分别43、44、30、43题。图\ref{fig:ch2-model-types}选取14B的关键对照，避免将两种模型、全部方法和四项消融塞入一张图；全部实测记录的类型结果见附录表\ref{tab:ch2-model-types}。类型反映资料整合与条件辨析要求，不直接代表难度，小类型尤其容易受少数题影响。

\begin{figure}[htbp]
\centering
\includegraphics[width=0.98\linewidth]{assets/chapter2/dev160_test40/fig2_model_types.pdf}
\caption{14B关键对照的分类型主得分。共用色标，格内保留未知范围，各列标明实际题数；完整表格见附录。}
\label{fig:ch2-model-types}
\end{figure}

开发与测试题目及主题不重叠；测试覆盖5个知识组，与开发共享热力模型知识组和少量原文。测试考查未用于调参的问题，不据此推断未见知识库或跨领域泛化。五组完整结果及必要点、条件正确率等辅助指标见附录。
\FloatBarrier

\subsection{同协议配对比较与检验分辨率}

统一展示全部方法后，配对统计仍以实际运行协议为边界。原运行中完整图对五个基线、两项消融分别校正；复验中完整图对BM25、BGE-M3、BM25+BGE-M3、BM25父上下文四项主比较及两项新消融分别校正。表\ref{tab:ch2-model-comparisons}把这些已冻结比较放在同一表，不追加跨消费者的确认性检验，也不因结果合并而改写原校正族。

\input{assets/chapter2/dev160_test40/comparisons.tex}

14B原运行完整图相对BM25的EAS差值识别范围为$[10.9,16.8]$分，相对基础搜索为$[31.6,33.6]$分，Holm校正$p$值上界分别为0.5000和0.3125。复验主比较及两项新消融的校正$p$值上界均不小于0.75。全部测试比较均未达到0.05阈值。

测试只有5个知识组，即使确定差值全部同向，双侧精确符号检验的最小未校正$p$值仍为0.0625。当前检验无法在0.05下确认优势，不能沿用全200题24组的显著结论。未知差值识别范围、bootstrap包络和实际意义阈值分别报告；未达阈值不证明方法等效，描述性排名也不证明普遍优势。
\FloatBarrier

\subsection{四项机制消融的统一分析}

表\ref{tab:ch2-model-ablations}同时列出来源关联、中文别名、关系遍历和上下文交付四项消融，各自对照相同消费者下的完整图。原运行14B完整图、去来源关联和去中文别名的EAS分别为62.0、58.5--59.4和61.0分，完整有效率为37.5\%、25.0\%和30.0\%。8B两项消融分别为29.0--35.8和24.4--30.0分。

\input{assets/chapter2/dev160_test40/ablations.tex}

复验完整图为57.4--60.5分，关闭遍历为58.6--63.6分，仅交付锚点为38.3--41.5分。关闭遍历没有稳定下降，不能支持关系遍历不可或缺；仅锚点交付出现较大描述性下降，但同时改变了父内容、相邻补充和锚点粒度，不能将下降归为父内容的单独贡献。去来源关联也同时改变结构、排序加分与上下文访问规则，不等同于仅删除跨文件边。

四项消融均未通过当前保守校正检验。某些问题中增加资料有帮助，不代表每条边、别名或补充段落均有独立正收益。各机制可能改变有限候选与字符预算中的竞争，其作用仍需结合固定查询和自主问答分别解释。
\FloatBarrier

\subsection{固定查询下的取证与预算}

为区分后端定位能力与回答模型的行动选择，固定查询实验直接使用原自然问题，不运行回答模型或参考答案改写。所有11种检索与消融配置共用2000、4000、6000字符的实际序列化预算，路径、行号和JSON包络均计入。原6600份交付按同一划分归集为开发5280份与测试1320份；图\ref{fig:ch2-fixed-query}和表\ref{tab:ch2-fixed-query}以测试40题为分母，没有重新查询或调参。

\begin{figure}[htbp]
\centering
\includegraphics[width=\linewidth]{assets/chapter2/dev160_test40/fig2_retrieval_budget.pdf}
\caption{固定自然问题下的预算与证据取得。完整登记证据召回与整题证据集合取得分别计算；原文曾取得不等于最终回答正确。}
\label{fig:ch2-fixed-query}
\end{figure}

\input{assets/chapter2/dev160_test40/retrieval.tex}

6000字符预算下，完整图的完整证据召回为79.2\%，BM25为57.5\%，BGE-M3为42.5\%，E5为1.2\%；BM25+E5、BM25+BGE-M3和父上下文分别为27.1\%、49.2\%和52.9\%。这些值衡量取得登记证据的完整行段，不是穷尽相关性池的语义召回，也不直接说明回答质量。历史E5按512 token递归分段，而BGE复用BM25名义1500字符与4行重叠分段，完整证据指标对分段粒度敏感；部分行命中另列，不能把低完整召回解释为完全没有相关内容。

关闭遍历的完整召回同为79.2\%，去中文别名为80.4\%，去来源关联为65.4\%，仅锚点为21.7\%。这与自主问答中工具采用、查询改写和停止决策共同形成的结果不同。固定查询用于检查原文定位与交付边界，不将其作为最终回答正确性的替代指标。
\FloatBarrier

\subsection{自主取证、引用送达与资源消耗}

自主问答中，原完整图在8B有15题使用工具，14B有40题使用工具；必要原文召回分别为22.9\%和71.7\%。原14B的BM25为59.2\%，基础搜索为1.2\%。表\ref{tab:ch2-model-process}将E5、BGE及其他实测方法纳入同一过程表。这些指标包含自主查询、补读与停止决策，不称为固定查询后端的Recall@K或MRR；引用坐标送达也不等于语义蕴含。

\input{assets/chapter2/dev160_test40/process.tex}

\input{assets/chapter2/dev160_test40/costs.tex}

资源消耗按原回执的测试ID归集，包含失败，不把记录迁移或复用算作新增消费。8B基线复用、基础搜索后补及复验的负载不同，耗时不作为受控速度结论；构图、编码和裁判成本另计。人评校准与图谱抽查均待真实标签，现有AI得分不能解释为独立人工验证后的准确率。
\FloatBarrier
''',encoding='utf-8')
    design='docs/chap02_knowledge_qa_design.tex'
    edit(design,'以及来源关联与中文别名分别起到什么作用。',
         '以及来源关联、中文别名、关系遍历与上下文交付分别起到什么作用。')
    edit(design,'比较包括来源图、BM25、E5、混合检索、基础搜索和模型直接作答六组。',
         '比较统一包括来源图、BM25、E5 Dense、BGE-M3 Dense、BM25+E5、BM25+BGE-M3、BM25父上下文、基础搜索和模型直接作答九种方法。E5和BGE均作为语义Embedding对照，BGE-M3是唯一新增编码器，仅启用Dense，不使用Sparse或ColBERT通道。')
    edit(design,'来源图、BM25、E5与混合检索四组均开放相同的目录浏览、原文阅读和方法检索工具。',
         '来源图与六种文本检索组均开放目录浏览、原文阅读和方法检索工具。')
    edit(design,'四组使用同一提示、工具描述和资源约束，方法名称不进入模型输入；图组只访问持久化图和原文，BM25、E5及混合组不加载来源图。',
         '同协议组使用相同中性提示、工具描述和资源约束，方法名称不进入模型输入；图组只访问持久化图和原文，各文本基线不加载来源图。原运行与公共逐行去重复验消费者分别保留协议身份。')
    edit(design,'混合组以互惠排名融合二者结果。',
         'BM25+E5以互惠排名融合二者结果；BM25+BGE-M3使用同样每路64候选、常数60的RRF。BGE采用BM25原文分段，而历史E5还受512 token递归拆分约束，二者不是只替换向量模型的严格单变量实验。BM25父上下文由独立原文解析器恢复同文件标题或字典层次，补充上限1200字符，不访问图节点、别名或来源所属标签。')
    edit(design,'混合检索 & 目录、原文读取 & BM25与E5排名融合',
         'BM25+E5 & 目录、原文读取 & BM25与E5排名融合 \\\\\nBGE-M3 Dense & 目录、原文读取 & BGE-M3向量相似度 \\\\\nBM25+BGE-M3 & 目录、原文读取 & BM25与BGE排名融合 \\\\\nBM25父上下文 & 目录、原文读取 & BM25定位、原文层次恢复')
    edit(design,'两项消融从本文完整图分别删减。',
         '四项消融分别从相同协议的完整图删减。前两项为去来源关联、去中文别名；后两项分别关闭关系遍历或仅交付锚点，统一列于结果部分。')
    anchor='结构化条件组织在正式方法确定前已移除，不属于本轮两项消融的对象。'
    edit(design,anchor,'结构化条件组织在正式方法确定前已移除，不作为这四项消融的对象。关闭遍历保留字段、别名、种子和上下文，关闭两条候选关系导航路径；仅锚点保留定位和候选顺序，只取消父/邻补充，不用剩余预算增加候选。后者包含交付粒度变化，不能解释为父内容的单独贡献。')
    edit(design,'两种规模使用相同题库、正式图和预算，',
         '此为原运行身份；另有14B的完整图/BM25复验、三项新增文本基线和两项新消融，共1400个原200题会话。合计4600会话按模型与开发/测试实体统一管理，开发3680、测试920，不把复验次数当作不同方法数。新增五项未在8B运行。两种规模使用相同题库、正式图和预算，')
    edit(design,'图谱对五个基线为主比较族，图谱对两种删减为消融族，分别进行Holm校正',
         '原运行图谱对五个基线为主比较族、对两种删减为消融族；复验对四个文本基线和两项新消融分别构成比较族。统一总表保留各自确认性范围，分别进行Holm校正')
    edit(design,'题型配额均衡保证了描述性比较的分母一致，不能使主题变体成为独立样本。',
         '各方法在相同测试ID上保留一致分母，但测试类型并非均衡，主题变体也不是独立样本。')
    appendix='docs/appendix_ch02.tex'
    edit(appendix,r'原始问答和评分也按模型与子集实体存放于\path{round2_20261020/split160_40_20261020/<model>/development}及\path{<model>/test}，各自含\path{generation/}、\path{scoring/}、\path{scoring_payloads/}和统计，不混用开发与测试记录；原件哈希映射见各目录\path{physical-records.json}。',
         r'原始问答和评分实体统一存放于\path{current/qwen3-8b}和\path{current/qwen3-14b}，各模型分别维护\path{development/}和\path{test/}；其中\path{generation/}、\path{scoring/}及\path{scoring_payloads/}均按方法、原运行或复验、题目ID组织。\path{current/results.json}统一维护方法与运行身份，\path{current/physical-records.json}绑定每份实体与原始回执哈希。E5和BGE均保留，完整图/BM25两次结果不平均或择优。')
    edit(appendix,r'\input{assets/chapter2/dev160_test40/round2/development.tex}'+'\n'+r'\input{assets/chapter2/dev160_test40/round2/comparisons.tex}',
         '% All original and added methods are included in the unified tables above.')
    for name in ['docs/abstract.tex','docs/chap05.tex']:
        edit(name,'复用Qwen3-8B与Qwen3-14B的六方法及两项消融回答和匿名14B评分，',
             '统一复用Qwen3-8B与Qwen3-14B已运行的九种方法、四项消融及匿名14B评分，保留E5和BGE两种向量对照，完整图/BM25原运行与复验分列，')
        edit(name,'测试仅含5个知识组，',
             '14B完整图复验为57.4--60.5分，BGE为51.1分，E5为36.6分；两种Embedding记录仍包含分段和运行协议差异。测试仅含5个知识组，')
    edit('docs/abstract.tex','reused for six methods and two ablations.',
         'reused in a unified comparison of nine methods and four ablations, including both E5 and BGE-M3. Original and replication graph/BM25 runs remain separate rows rather than being averaged.')
    edit('docs/abstract.tex','Ranges retain unknown judgments.',
         'The 14B graph replication scores57.4--60.5; BGE-M3 scores51.1 and historical E5 scores36.6, with segmentation and consumer differences retained. Ranges retain unknown judgments.')
    for name in ['docs/chap01.tex','docs/chap05.tex']:
        path=ROOT/name;text=path.read_text(encoding='utf-8')
        for old,new in [('复用8B与14B六方法及两项消融结果','统一比较已实测九种方法与四项消融，保留E5和BGE及原运行/复验身份'),
                        ('复用六方法、两项消融和冻结AI评分','统一呈现九种方法、四项消融及冻结AI评分'),
                        ('复用8B与14B六方法和两项消融结果','统一呈现已实测九种方法与四项消融，8B未运行的新方法不填推测值')]:text=text.replace(old,new)
        path.write_text(text,encoding='utf-8')
    path=ROOT/'docs/chap02.tex';text=path.read_text(encoding='utf-8').replace('并通过两项消融分析来源关联和中文别名的作用。',
        '统一比较包含E5和BGE的九种方法，并通过四项消融分析来源关联、别名、关系遍历及上下文交付的作用。').replace(
        '原两项消融检验来源关联和中文别名，第二轮另行检验关系遍历与仅锚点交付。',
        '四项消融统一检验来源关联、中文别名、关系遍历与仅锚点交付，分别使用同协议完整图参照。').replace(
        '复用8B与14B的六方法和两项消融原始结果。',
        '统一呈现已实测九种方法与四项消融，保留E5、BGE及完整图/BM25两次运行身份。').replace(
        '相关机制具有描述性差异；',
        '14B复验完整图为57.4--60.5分、BGE为51.1分、E5为36.6分，相关机制具有描述性差异；')
    path.write_text(text,encoding='utf-8')
    print('Unified design/results/abstract/conclusion and appendix updated')


if __name__=='__main__':main()
