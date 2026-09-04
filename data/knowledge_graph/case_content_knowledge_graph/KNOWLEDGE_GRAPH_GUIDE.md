
# BlastFoam 算例知识图谱解读指南

## 1. 简介

本文档旨在详细阐述 "BlastFoam 算例知识图谱" 的结构、目的和应用方式。该知识图谱的核心目标是将一个完整的 blastFoam 算例（包含其所有相关的物理设置、数值方案和控制参数文件）转换为一个单一的、结构化的 JSON 文件。

这种转换使得大型语言模型（LLM）和 AI 编程助手能够：

*   **快速理解**：在几秒钟内掌握一个复杂算例的核心物理设置和模拟目标。
*   **精确定位**：当用户提出修改需求时（例如“修改爆炸物位置”），能准确找到对应的文件和参数。
*   **自动化操作**：为自动化修改、比较和生成新算例奠定数据基础。

知识图谱中的每一个 JSON 文件都代表一个独立的 blastFoam 算例的完整知识图谱。每个 JSON 文件的命名方式是将其在教程库中的相对路径使用下划线 `_` 拼接得到的。例如，路径为 `blastFoam/building3D` 的算例，其对应的知识图谱文件名为 `blastFoam_building3D.json`。

## 2. 知识图谱结构

每个 JSON 文件都代表一个独立的知识图谱，其结构专为图数据库（如 Neo4j）设计，包含 `nodes` 和 `relationships` 两个顶级字段。

```json
{
  "nodes": [ ... ],
  "relationships": [ ... ]
}
```

这种结构将算例的组成部分（如文件、变量、参数）抽象为图中的“节点”，将它们之间的关系（如文件包含变量）抽象为图中的“边”。

### 2.1 `nodes` (节点)

`nodes` 是一个对象数组，其中每个对象代表图中的一个节点。一个节点可以是算例本身、一个文件或文件中的一个变量/关键词。

每个节点对象都包含以下字段：

*   `id` (string): 节点的唯一标识符。
    *   *示例 (Case)*: `"blastFoam/building3D"`
    *   *示例 (File)*: `"blastFoam/building3D/system/controlDict"`
    *   *示例 (Variable)*: `"Variable_endTime"`
*   `label` (string): 节点的类型或分类。常见的标签有：
    *   `Case`: 代表整个算例。
    *   `File`: 代表一个具体的文件。
    *   `Variable`: 代表文件中的一个变量、关键词或参数。
*   `properties` (object): 包含节点的详细属性。
    *   *`Case` 节点的属性*:
        ```json
        { "name": "building3D", "path": "blastFoam/building3D" }
        ```
    *   *`File` 节点的属性*:
        ```json
        { "name": "controlDict", "path": "blastFoam/building3D/system/controlDict" }
        ```
    *   *`Variable` 节点的属性*:
        ```json
        { "name": "endTime", "type": "Parameter" }
        ```
        其中 `type` 字段进一步细化了变量的种类，如 `Parameter`, `Keyword`, `BoundaryCondition`, `NumericalScheme` 等。

### 2.2 `relationships` (关系)

`relationships` 是一个对象数组，定义了节点之间的连接关系（即图的边）。

每个关系对象包含以下字段：

*   `source` (string): 关系起始节点的 `id`。
*   `target` (string): 关系目标节点的 `id`。
*   `type` (string): 描述关系的类型。最常见的关系类型是：
    *   `CONTAINS`: 表示一个算例（Case）包含一个文件（File）。
    *   `DEFINES`: 表示一个文件（File）定义或使用了一个变量（Variable）。

*示例关系*:
```json
[
  {
    "source": "blastFoam/building3D",
    "target": "blastFoam/building3D/system/controlDict",
    "type": "CONTAINS"
  },
  {
    "source": "blastFoam/building3D/system/controlDict",
    "target": "Variable_endTime",
    "type": "DEFINES"
  }
]
```
这个例子表示 `building3D` 算例包含了 `controlDict` 文件，而 `controlDict` 文件定义了 `endTime` 这个变量。

## 3. 如何使用

这份图谱化的数据是连接用户自然语言需求和底层代码文件的桥梁，尤其适合在图数据库中进行查询和分析。

### 3.1 场景一：快速理解算例

要快速了解一个算例，可以首先找到 `label` 为 `Case` 的节点，然后追踪它 `CONTAINS` 的所有 `File` 节点，从而了解算例由哪些文件构成。

### 3.2 场景二：精确定位文件

如果用户提出：“我想把模拟结束时间改成 0.2 秒”，AI 助手可以执行以下操作（这在图数据库中使用 Cypher 等查询语言会非常高效）：

1.  **查找变量节点**：在所有 `nodes` 中，找到 `properties.name` 为 `endTime` 且 `label` 为 `Variable` 的节点。
2.  **反向追溯关系**：在 `relationships` 中，查找哪个 `File` 节点的 `id` 作为 `source`，连接到上一步找到的 `endTime` 变量节点的 `id` (`target`)，且关系类型为 `DEFINES`。
3.  **识别文件**：通过上述关系，可以精确定位到 `blastFoam/building3D/system/controlDict` 这个文件。
4.  **执行修改**：读取原始 `system/controlDict` 文件，将 `endTime` 的值修改为 0.2。

### 3.3 场景三：跨案例分析与比较

通过将多个 JSON 文件导入图数据库，可以进行强大的跨案例分析：

*   **查询**：“找出所有定义了 `JWL` 方程（`Variable` 节点，`name` 为 `JWL`）的算例。”
*   **统计**：“在所有算例中，`system/fvSchemes` 文件最常用的 `ddtSchemes` 是什么？”
*   **比较**：“`building3D` 和 `building3DWorkshop` 两个算例使用了哪些不同的 `Variable`？”

## 4. 总结

BlastFoam 算例知识图谱通过将非结构化的字典文件转化为图数据库友好的 JSON 格式，极大地增强了机器对 CFD 算例的结构化理解能力。它不仅能提升 AI 编程助手的智能水平，也为算例数据的管理、复杂查询和自动化分析提供了强大的数据基础。
