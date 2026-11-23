# PIPE-01 稳态层流开发验证

从空工程建立直圆管内不可压、充分发展、轴对称的稳态牛顿流体数值算例。半径 0.01 m，动力黏度 0.001 Pa·s，沿轴线压力下降率 0.8 Pa/m。中心满足对称条件，壁面无滑移。使用 64 个径向均匀区间，从轴线到壁面共 65 个节点。

自行离散动量方程并生成 case.json。共同计算节点接口接收 65 行三对角系统，每行依次为半径（m）、下对角、主对角、上对角、右端项；JSON 根对象只有 rows。节点使用固定的三对角求解器，返回 profile.csv（r_m,u_m_s）。禁止本地求解或用解析值代替数值结果。

用 python common/pipe_client.py submit 登记本次 case.json，使用 python common/pipe_client.py collect 等候结果。collect 可重复读取，只提交一次。最终在 delivery/ 中交付可复跑的离散化源码、case.json、节点原始 profile.csv 和节点回执、独立后处理源码及其输出 summary.json（center_m_s、flow_m3_s），以及 README.md。说明物理假设、边界、离散、积分、复跑步骤及数值与解析解的差异。验收检查全部节点与解析速度的最大绝对差不超过 0.0001 m/s，体积流量相对误差不超过 1%。仅用本题工作区和本臂工具。
