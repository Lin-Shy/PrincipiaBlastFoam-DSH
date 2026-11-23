---
name: s10-history-delivery
description: 用已回收的 S10 原生测点和作业回执交付全时间轴压力数据，不发起求解。
---

当任务要求交付原生压力时程时，先确认输入提供了原生 p、对应 run.json 和任务 conditions.json。运行本开发副本的 export_delivery.py，位置参数依次是这三份文件（p、conditions.json、run.json）和一个未存在的输出目录。将生成的 pressure.csv、observations.json 及其引用原件一并交付。CSV 保留全部原生时刻，不用指定指标窗截短原件。回执缺失时说明无法核对作业身份，不编造回执。将历史求解与本轮数据转换分开署名。此工具不提供预测精度判断。
