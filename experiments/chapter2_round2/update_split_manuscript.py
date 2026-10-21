"""Synchronize manuscript scope from real split summaries, without rescoring."""
from common import *
from split_existing200 import OUT,SPLIT

ROOT=WORKSPACE/'graduation-thesis-materials/graduation-manuscript'
DOCS=ROOT/'docs'

def replace(path,old,new):
    text=path.read_text(encoding='utf-8')
    if old not in text:
        if new in text:return
        raise ValueError('missing edit anchor: '+str(path)+' '+old[:45])
    path.write_text(text.replace(old,new),encoding='utf-8')

def paragraph(path,prefix,new):
    text=path.read_text(encoding='utf-8');parts=text.split('\n\n');found=[i for i,p in enumerate(parts)if any(line.startswith(prefix)for line in p.splitlines())]
    if not found and new in text:return
    if len(found)!=1:raise ValueError('ambiguous paragraph: '+prefix)
    before=parts[found[0]].split(prefix,1)[0];parts[found[0]]=before+new;path.write_text('\n\n'.join(parts),encoding='utf-8')

def main():
    p=read(SPLIT);test={m:read(OUT/m/'test/summary.json')for m in ['8b','14b']};dev={m:read(OUT/m/'development/summary.json')for m in test}
    def bounds(v,stem='score'):return f"{100*v[stem+'_lower']:.1f}--{100*v[stem+'_upper']:.1f}"
    g8=test['8b']['by_arm']['graph'];g14=test['14b']['by_arm']['graph'];b14=test['14b']['by_arm']['bm25']
    design=DOCS/'chap02_knowledge_qa_design.tex'
    paragraph(design,'实验检验三个问题：','实验检验三个问题：来源图能否改善专业问答的最终质量，这种作用是否随资料整合和条件辨析需求变化，以及来源关联与中文别名分别起到什么作用。原200题划分为160题开发集和40题测试集，采用已有调参设置；以下主要质量比较与检验以40题测试集为范围，160题结果单独作开发阶段描述，不按成绩重新选题。')
    paragraph(design,'评分侧登记537个必要点',r'评分侧登记537个必要点和143个必要证据单元，证据涉及42份原文；8组成对问题通过条件变化考查结论是否相应改变。题库全部200道问题均已逐题人工审核通过，构建与审核过程见附录\ref{app:ch2-evidence}。其中原有160题用于方法开发和参数调优，另40题为从未参与调参的未见留出集。各方法直接采用已完成调优的设置，本次按已有题目身份复用原回答、评分及文件，不另建题库，不重新生成或评分。调参过程与旧记录未同步的更正依据及划分清单在附录保留；题目审核不等同于评分标注或AI裁判准确率的独立验证。')
    anchor='生产语料由独立清单确定'
    paragraph(design,anchor,r'开发集覆盖55个主题、20个知识组，四类分别43、44、30、43题；测试集覆盖14个主题、5个知识组，四类分别7、6、20、7题，其中13题需条件辨析。两部分题目ID与主题均不重叠，但共享一个既有知识组及部分原文，因此未见题目不等于未见文档。测试集的组成源于既有40题身份，不为类别均衡或方法得分再次抽选。生产语料由独立清单确定，不按评分支持文件筛选；构图和问答输入不包含参考答案、必要点或评分意见。')
    paragraph(design,'主指标为端到端有效回答得分，保留完整有效率',r'主指标为端到端有效回答得分，保留完整有效率作为整题全对指标。两者都评价最终回答：主得分区分正确且适用的部分解释，完整有效率要求所有必要知识充分表达。生成失败或未交付有效最终回答均计0，裁判未知保留上下界。下式中测试集取 $n=40$，开发集描述取 $n=160$，各方法均保留对应完整分母。')
    replace(design,r'\frac1{200}\sum_{i=1}^{200}',r'\frac1n\sum_{i=1}^{n}')
    replace(design,r'\frac{100}{200}\sum_{i=1}^{200}',r'\frac{100}{n}\sum_{i=1}^{n}')
    replace(design,r'$100\sum_iV_i/200$',r'$100\sum_iV_i/n$')
    replace(design,'必要点覆盖率和100道条件题上的条件正确率','必要点覆盖率和测试集13道条件题上的条件正确率')
    paragraph(design,'各模型分别对相同问题上的方法结果作配对比较',r'各模型分别对40道测试题上的方法结果作配对比较，考虑测试集实际5个预定义知识组内的相关性。本文报告40题微平均和5组等权宏平均，并按这5组配对bootstrap计算差值的百分位95\%区间\citep{ch2-efron1979}；开发160题仅作描述。主得分存在未知时，归一化差值识别范围为 $[\overline S_A^- -\overline S_B^+,\overline S_A^+ -\overline S_B^-]$，报告时乘100；两端分别重采样构成包络。识别范围与组重采样区间不混称，模型规模差异只作描述性分析。')
    paragraph(design,'基础搜索是在观察原五方法结果后增加的对照',r'基础搜索是在观察原五方法结果后增加的对照，另批次运行；主比较族由四项扩展为五项后重新校正，既有逐题回答与评分保持原样。图与指标的修订历史及8B基线复用身份仍予披露。当前160/40角色依据研究者对实际调参范围的更正补录，测试结果直接复用既有回执，不将此次重汇总写为新一轮生成或新评分。5组的双侧精确符号检验最小可达未校正$p$值为 $2/2^5=0.0625$，不能沿用全200题、24组统计的显著性结论。该测试考查未用于调参的问题，不推断未见文档或仿真物理正确性。')
    text=(DOCS/'chap02_knowledge_qa_results.tex')
    contents=r'''% !TeX root = ../main.tex
\section{实验结果与分析}
\label{sec:ch2-qa-results}

\subsection{40题未见留出测试集的总体回答质量}

表\ref{tab:ch2-model-scales}比较两种模型在40题测试集上的既有回答，开发160题的结果单独列于附录。8B完整图的端到端有效回答得分为G8分，14B为G14分；14B的BM25为B14分。完整图在两种规模的六方法中均取得最高得分下界，范围保留裁判未知，不是重复运行的置信区间。所有数值来自原回答与评分按ID归集，未新增模型调用或修改评分。

\input{assets/chapter2/dev160_test40/overall.tex}

完整有效率要求整题全部必要知识、事实与条件均通过。8B完整图为C8\%，14B为C14\%，14B的BM25为CB14\%。主得分区分正确且适用的部分解释，因此较高EAS不等于相同比例的问题全部答对。模型规模差异仍包含工具采用及既有批次差异，不能解释为相同证据条件下纯推理能力的提升。

\begin{figure}[htbp]
\centering
\includegraphics[width=\linewidth]{assets/chapter2/dev160_test40/fig2_model_scales.pdf}
\caption{40题测试集的最终回答质量。点为下界，线段延至裁判未知上界；分隔线以下为消融。}
\label{fig:ch2-model-quality}
\end{figure}

\subsection{题型与知识组差异}

测试集四类分别7、6、20、7题，开发集四类分别43、44、30、43题。表\ref{tab:ch2-model-types}与图\ref{fig:ch2-model-types}报告测试集的实际组成与结果，不将全200题的四类各50题误写为测试集均衡。类别描述资料整合和条件辨析要求，不直接代表难度；较小类型的结果对少数题目更敏感。

\begin{figure}[htbp]
\centering
\includegraphics[width=0.98\linewidth]{assets/chapter2/dev160_test40/fig2_model_types.pdf}
\caption{40题测试集的分类型主得分。两种模型共用色标，格内保留未知范围，列中标注实际题数。}
\label{fig:ch2-model-types}
\end{figure}

开发与测试题目及主题不重叠；测试题覆盖5个知识组，与开发集共享热力模型知识组和少量原文。故本节检验未用于调参的题目，不以题目划分宣称未见知识库或跨领域泛化。完整的5组结果及辅助质量见附录。
\FloatBarrier

\subsection{配对比较与检验分辨率}

表\ref{tab:ch2-model-comparisons}按测试集实际5组重新执行知识组配对统计。14B完整图相对BM25的EAS差值识别范围为$[10.9,16.8]$分，相对基础搜索为$[31.6,33.6]$分；两者得分差距均为正。但五项主比较分别校正后的$p$值上界为0.5000和0.3125，均未达到0.05。8B的五项主比较也均未通过校正检验。

\input{assets/chapter2/dev160_test40/comparisons.tex}

测试集只有5个知识组，即使所有组的确定差值同向，双侧精确符号检验的最小未校正$p$值仍为0.0625。当前检验因此无法在0.05阈值下确认统计优势；不能把全200题24组分析中相对基础搜索或直接作答的显著结果转移到40题测试集。得分识别范围、bootstrap包络、实际意义阈值和保守检验分别报告。未达到检验阈值不证明方法等效，也不能仅凭描述性均值排名断言普遍优势。
\FloatBarrier

\subsection{来源关联与中文别名消融}

表\ref{tab:ch2-model-ablations}复用相同40题的图谱消融回答。14B完整图、去来源关联和去中文别名的EAS分别为62.0、58.5--59.4和61.0分；完整有效率分别为37.5\%、25.0\%和30.0\%。8B完整图EAS为32.3--38.1分，两项消融分别为29.0--35.8和24.4--30.0分。

\input{assets/chapter2/dev160_test40/ablations.tex}

14B去来源关联后的必要原文召回由71.7\%变为66.2\%，去中文别名后为69.2\%。更多完整来源在部分题目中转化为完整回答，但两种模型的两项消融均未通过当前测试集保守校正检验。消融反映相应结构、排序与访问规则的共同影响，不证明每条边或每个别名都有独立正收益。父内容、相邻扩展与锚点尚不能由这两项历史消融单独分离。
\FloatBarrier

\subsection{实际取证、引用送达与资源消耗}

40题测试集中，8B完整图有15题使用工具，14B有40题使用工具；完整图的必要原文召回分别为22.9\%和71.7\%，BM25分别为14.2\%和59.2\%。14B基础搜索工具采用36题，完整登记证据召回为1.2\%。字面行命中可以提供线索，但未取得登记证据的完整行段时仍按统一口径记为未完整取得，不能解释为从未读到相关内容。

\input{assets/chapter2/dev160_test40/process.tex}

这些过程指标包含自主查询、补读和停止决策，不是固定查询下的纯后端Recall@K或MRR。引用坐标全部送达只证明资料曾被取得，不等于语义蕴含。取证增加可以改善回答条件，必要知识遗漏、事实错误与条件结论仍需回答模型处理。

\input{assets/chapter2/dev160_test40/costs.tex}

资源按原回执中的40题归集，包含失败会话，不将复用文件计作新增消费。8B基线复用、基础搜索后补以及各批次负载不同，耗时不作为受控速度结论；离线构图、编码与裁判成本另计。开发160题的结果只描述既有调参设置，不用于重新选择测试子集或修订评分。
\FloatBarrier
'''
    for key,value in [('CB14',bounds(b14,'complete')),('G8',bounds(g8)),('G14',bounds(g14)),('B14',bounds(b14)),('C8',bounds(g8,'complete')),('C14',bounds(g14,'complete'))]:contents=contents.replace(key,value)
    text.write_text(contents,encoding='utf-8')
    chapter=DOCS/'chap02.tex'
    replace(chapter,'再以200题专业知识问答集比较最终回答质量','再将200题专业知识问答集分为160题开发集和40题未见留出测试集，以测试集比较最终回答质量')
    paragraph(chapter,'本文在14B运行前固定当前完整图与主指标',r'本章采用已完成调优的设置，将原200题中的160题作为开发集、40题作为未见留出测试集。研究者更正了此前未同步的调参范围记录，划分沿用已有题目身份，原回答、评分和执行时间不变。图与主指标的修订、8B基线复用及基础搜索后补身份仍予保留；裁判与14B回答模型同系列同规模，各组仅单次生成。这些限制不由题目划分消除。')
    paragraph(chapter,'AI评分的合成控制不能替代人工准确率验证',r'AI评分的合成控制不能替代人工准确率验证，未知边界和知识组重采样不涵盖全部系统误差。40题测试集仅含5个知识组，预定义类型也不均衡，保守检验分辨率有限；开发与测试共享部分原文。因此，未见题目结果不扩展为未见文档或物理仿真有效性。')
    paragraph(chapter,'200题实验分别完成8B与14B的六方法比较',f'本章采用160题开发、40题未见留出测试的评价安排，复用8B与14B的六方法和两项消融原始结果。40题测试集上，完整图主得分分别为{bounds(g8)}分和{bounds(g14)}分；14B完整有效率为{bounds(g14,"complete")}\\%，BM25为{bounds(b14,"complete")}\\%。图谱在两种规模下取得较高得分下界，相关机制具有描述性差异；但5个知识组上的保守检验尚未确认稳定优势。必要知识遗漏、事实约束、同系列AI测量、批次和小样本仍限制推断。第3章独立研究DSH领域系统，不由本章问答指标推断仿真效果。')
    summary=f'在专业知识问答方面，本文以来源图连接模型定义、实例配置和准确原文，由同一智能体自主检索并整合解释。200题覆盖69个主题、24个知识组，其中160题用于开发与调参，40题作为从未参与调参的未见留出测试集。复用Qwen3-8B与Qwen3-14B的六方法及两项消融回答和匿名14B评分，主指标为端到端有效回答得分，保留严格完整有效率。测试集上完整图主得分分别为{bounds(g8)}分和{bounds(g14)}分；14B完整有效率为{bounds(g14,"complete")}\\%，BM25为{bounds(b14,"complete")}\\%。得分范围保留裁判未知。测试仅含5个知识组，保守校正检验尚未确认统计优势；知识遗漏、事实错误、同系列AI测量与批次差异限制结论。'
    paragraph(DOCS/'abstract.tex','在专业知识问答方面，',summary)
    paragraph(DOCS/'abstract.tex','This thesis studies LLM-driven blast-flow simulation',r'This thesis studies LLM-driven blast-flow simulation with OpenFOAM/blastFoam. A source-bound graph links model definitions, case configurations, and original evidence for autonomous professional question answering. The 200-question bank spans 69 themes and 24 knowledge groups: 160 questions are used for development and tuning, and 40 are held out as unseen questions that never participated in tuning, as confirmed by the researcher when correcting unsynchronized records. Existing Qwen3-8B and Qwen3-14B answers and anonymous 14B judgments are reused for six methods and two ablations. On the 40-question test set, graph EAS is 32.3--38.1 with 8B and 62.0 with 14B; 14B strict validity is 37.5\%, versus 20.0--22.5\% for BM25. Ranges retain unknown judgments. With only five test knowledge groups, conservative adjusted testing does not establish statistical superiority. The split does not imply unseen documents; shared-family judgments, batch differences, single generations, and limited group counts constrain inference.')
    paragraph(DOCS/'chap01.tex','（1）面向blastFoam的知识图谱增强专业问答。','（1）面向blastFoam的知识图谱增强专业问答。以来源图组织专业对象、资料关联与原文条件，由同一智能体取得原文并形成回答。200题按既有身份分为160题开发集和40题未见留出测试集，采用已调优设置，复用8B与14B六方法及两项消融结果。主得分结合必要点覆盖与事实、条件门控，保留失败、未知和严格整题指标；测试按实际5知识组分析，理论性质不作为实测优势。')
    paragraph(DOCS/'chap01.tex','第2章研究知识图谱增强的专业知识问答，','第2章研究知识图谱增强的专业知识问答，定义必要知识、完整性和适用性，设计来源图与自主补充机制，并给出条件性论证及反例。200题划分为160题开发和40题未见留出测试，复用六方法、两项消融和冻结AI评分，分别分析测试质量、题型、知识组、取证及资源，说明未确认结论与测量边界。')
    paragraph(DOCS/'chap05.tex','专业知识问答方面，',summary.replace('在专业知识问答方面，','专业知识问答方面，'))
    paragraph(DOCS/'chap05.tex','专业问答已完成8B与14B在200题上的六方法比较',r'专业问答采用160题开发、40题未见留出测试，复用8B与14B六方法和两项消融结果，32B尚待补充。测试只有5个知识组，类型构成不均衡；模型规模与工具采用共同变化，同系列AI评分和批次差异亦限制推断。DSH领域系统与单智能体RSI仍待独立验证，不能由问答成绩保证仿真可靠性或物理正确性。')
    appendix=DOCS/'appendix_ch02.tex'
    replace(appendix,'assets/chapter2/model_scales/','assets/chapter2/dev160_test40/')
    paragraph(appendix,'基础160题经人工审阅，',r'基础160题和原200题中的补充40题均已逐题人工审核通过。研究者于2026-10-20更正此前未同步的调参范围记录，确认仅160题用于开发和调参，40题为从未参与调参的未见留出集。本次依据原题库\texttt{dataset.json}已有\texttt{new\_ids}补录角色，不按成绩再抽样；原200题的生成、匿名评分与时间戳均保留，分割重汇总不等于新生成。ID及确认依据位于\path{graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json}，派生统计位于\path{round2_20261020/split160_40_20261020}。该确认不等同于独立人工评分准确率验证。')
    replace(appendix,r'双侧符号随机化枚举全部 $2^{24}$ 个组符号向量。',r'原全200题统计枚举 $2^{24}$ 个组符号向量；当前40题测试统计枚举 $2^5$ 个组符号向量。')
    replace(appendix,r'\section{生成与裁判的闭合状态}',r'\section{原全200题运行与测试子集闭合状态}'+'\n\n以下执行次数、token与原始失败数属于既有全200题活动，保持其真实身份；插入的状态表仅按当前40题测试ID归集，不将全量计数冒充测试集分母。')
    paragraph(appendix,'以下保留各方法与消融的必要点覆盖、条件正确率和24知识组宏平均。',r'以下列出40题测试集的必要点覆盖、13道条件题的条件正确率和5组宏平均，开发160题另表列出。全部统计复用冻结逐题指标，未知和失败不删除。')
    replace(appendix,r'\FloatBarrier'+'\n\n'+r'\section{未知结果下的配对检验边界}',r'\input{assets/chapter2/dev160_test40/development.tex}'+'\n'+r'\FloatBarrier'+'\n\n'+r'\section{未知结果下的配对检验边界}')
    replace(appendix,'令知识组 $g$ 对整体200题差值的贡献范围','令测试知识组 $g$ 对40题差值的贡献范围')
    replace(appendix,'求和并除以200得到','求和并除以40得到')
    replace(appendix,r'\{-1,1\}^{24}',r'\{-1,1\}^{5}')
    replace(appendix,r'p^+=2^{-24}',r'p^+=2^{-5}')
    paragraph(appendix,r'表\ref{tab:ch2-8b-groups}与表\ref{tab:ch2-14b-groups}分别保留',r'表\ref{tab:ch2-8b-groups}与表\ref{tab:ch2-14b-groups}列出测试集实际5个知识组，不按方法表现选组。题内必要点先归一化；宏平均对5组等权，微平均对40题等权。全部200题的原24组统计仍保存在原实验归档，不作为本节测试分母。')
    print('Updated design, results, abstracts, chapter1/2/5 and appendix to actual160/40 statistics')

if __name__=='__main__':main()
