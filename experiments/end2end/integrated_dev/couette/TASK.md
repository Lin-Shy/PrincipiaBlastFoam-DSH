# COUETTE-A01 修改壁面运动并交回流量与剪切

起始工程 initial_case.py 建立两无限平板之间、充分发展、不可压、稳态的牛顿流体层流矩阵。板间距 0.01 m，无轴向压降，流体动力黏度 0.002 Pa·s。起始下壁静止、上壁沿流向 +0.1 m/s。保持间距、64 个均匀区间和无滑移条件，将下壁速度改为 −0.02 m/s，上壁改为 +0.08 m/s。请交付实际修改后的工程。

从工作区根目录运行工程生成 case.json，然后用 `python common/pipe_client.py submit` 登记，`python common/pipe_client.py collect` 回收。节点按五列格式（横向位置、下对角、主对角、上对角、右端项）解三对角系统。原始表头 r_m 在此接口中表示从下壁到上壁的横向坐标 y，单位 m，u_m_s 为轴向速度。计算只在分配节点进行，各臂最多一个作业。禁止用本地求解或解析值代替节点输出。

在 delivery/ 交付可复跑的矩阵生成源码、case.json、节点原始 profile.csv 和 receipt.json，以及独立后处理源码、summary.json 和 README.md。summary.json 记录有符号的单位宽度体积流量 flow_per_width_m2_s，以及下壁流体应力分量 shear_xy_pa = μ·du/dy。按回收表积分和求导。说明使用的符号、单位、离散方法及复跑命令。验收按真实 JobID、退出状态和原件哈希核对，65 个速度对两壁之间线性解的最大绝对误差不超过 1e-8 m/s；流量与剪切的相对误差各不超过 0.1%。
