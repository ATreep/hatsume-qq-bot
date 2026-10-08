# 关于 venv
无论任何时候，禁止修改此项目的虚拟环境 .venv 目录内的任何文件。
如果你需要使用 pytest 测试，请使用本地的 python 环境进行测试，不要尝试查看或运行 .venv 环境。

# sandbox_computer_use agent LOOP

每次修改 `sandbox_computer_use` 的 Loop 逻辑，都必须同步更新本节。Loop 只保留
以下四个 Step；Jev 负责结构化选择，受限 LLM 分支负责需要自然语言理解、截图
分析或输入内容生成的操作，具体实现以代码为准：

1. **Step 1：检查桌面状态**。
   - 调用 `gui_inspect(application="", max_nodes=200)`，通过 AT-SPI 扫描整个桌面；
     该检查本身不调用 Jev 或 LLM。
   - 从返回的元素中整理出可见应用窗口；对 Chrome 窗口额外调用
     `chrome_inspect`，附加当前标签页 URL 和标题。
   - 检查失败由外层 Loop 记录为错误；未达到迭代上限时直接开始下一轮 Step 1。

2. **Step 2：选择要操作的窗口**。
   - 将任务、窗口列表、最近一次操作等状态提交给 Jev 的 `window_action` 选择题；
     Jev 只能从窗口 ID、`open_application`、`open_webpage`、`finish_report` 中选择。
   - 选择窗口 ID：进入 Step 3。
   - 选择 `open_application`：启动一次受限 LLM 分支，使用轻量模型和一次
     `gui_launch` 工具调用；分支可获得截图、桌面检查和 Chrome 检查上下文，工具返回后
     立即结束该 LLM 分支，然后进入 Step 4。
   - 选择 `open_webpage`：启动一次受限 LLM 分支，使用轻量模型和一次
     `chrome_open` 工具调用；分支可获得同样的桌面/Chrome上下文，工具返回后立即结束
     该 LLM 分支，然后进入 Step 4。
   - 选择 `finish_report`：启动受限 LLM 分支，用截图和 `view_image` 生成最终报告并结束；
     如果当前窗口列表包含 Chrome，同时将当前标签页的 `chrome_inspect` 提供给该 LLM。
   - Jev 返回非法选项时进入 `jev_fallback` 受限 LLM 分支；分支失败按外层错误处理。

3. **Step 3：检查选中窗口并选择目标操作**。
   - 对原生窗口调用 `gui_inspect(application=...)`，对 Chrome 窗口调用
     `chrome_inspect(target_id=...)`；元素用于生成 Jev 的 criteria，传给 Jev 的
     `inspection` 元数据不再包含完整 `elements` 列表；窗口状态保留最近一次 `gui_inspect`
     返回的应用根 `app_id`，供坐标拖拽激活目标窗口。
   - 日志需打印每个 Step 3 选择题实际提交给 Jev 的完整 criteria 值。
   - 原生窗口提交 `element_action`，Chrome 提交 `chrome_element_action`；每个元素的
     criteria 文本由 `nodeName` 与 `nodeValue` 拼接（兼容旧检查结果时回退到 `role` 与
     `name`）。Chrome criteria 还附加元素的 `role`、`value` 和 DOM `attributes`（包含属性值），
     不附加 Accessibility `properties`。Jev 再从元素 ID、`screenshot_coordinate_click`、`wait_before_operation`、
     `finish_report`、`screenshot_coordinate_drag` 中选择。
   - 选择 `screenshot_coordinate_click`：严格依次调用一次 `gui_screenshot`、一次
     `view_image`、一次 `gui_click_coordinates`；第三次调用完成后立即结束该分支，进入
     Step 4。不得重复截图、视觉分析或坐标点击，也不得调用其他工具。
   - 选择 `screenshot_coordinate_drag`：严格依次调用一次 `gui_screenshot`、一次
     `view_image`、一次 `gui_drag`；视觉分析必须提供拖拽起点和终点坐标，第三次调用完成后
     立即结束该分支，进入 Step 4。不得重复截图、视觉分析或拖拽，也不得调用其他工具。
   - 选择 `wait_before_operation`：记录等待动作，然后进入 Step 4。
   - 选择 `finish_report`：进入截图报告受限 LLM 分支并结束。
   - 选择元素 ID：再次调用 Jev。原生窗口使用 `native_operation`（`click`、
     `set_text`、`focus_key`、`focus_type`）；Chrome 使用 `chrome_operation`
     （`chrome_click`、`chrome_focus`、`chrome_set_text`；只有可编辑 role 才提供
     `chrome_set_text`）。直接点击/聚焦调用对应工具；
     文本输入、按键和输入生成使用一次受限 LLM 分支，工具返回后立即结束该分支并进入 Step 4。
   - `chrome_set_text` 分支使用轻量模型，并附加截图与最新 Chrome 检查；分支必须实际调用
     一次 `chrome_set_text`，由 Chrome CDP 先选中现有内容再通过 `Input.insertText` 输入并校验值，
     并在刷新检查后按 `backendNodeId` 重新绑定当前元素 ID，避免检查刷新使旧 ID 失效，
     以便受控输入框收到真实输入事件。原生输入分支使用代码模型；除
     `screenshot_coordinate_click` 分支固定执行上述三次调用，其他受限分支最多执行一次工具调用。
     Jev 返回非法选项时使用 `jev_fallback` 分支。
   - 受限分支在工具节点返回后关闭 LLM 流；关闭流时出现的 `GraphInterrupt` 视为内部
     停止信号，保留已返回的工具结果，不能把本次操作重新抛回外层 Loop。
   - Chrome 元素执行 `chrome_set_text` 后，下一轮暂时从 criteria 移除刚编辑的同一元素，
     并在 state 中提示选择提交/搜索控件，促使 Jev 选择搜索按钮等后续控件；该排除只
     持续一轮。
   - 每次完成的 Step 3 都会追加到 state 的 `step3_history`，上下文保留最近 3 个
     iteration 的元素/操作选择；如果操作是 `chrome_set_text`，该次受限 LLM 的返回值也
     会记录在对应条目中。若操作实际点击了 AT-SPI 或 CDP 元素，对应条目还记录
     `clicked_element` 的 `role`、`value`、`description`、`name` 与 `application`，供后续
     Jev 决策参考。`step3_decision` 与 `step3_llm_result` 继续提供最新一条记录。
   - 如果 Jev 连续 3 个 iteration 选择 `wait_before_operation`，下一轮的 criteria 暂时
     移除该选项；再下一轮恢复该选项。中间任何非 wait 选择都会清零连续计数。

4. **Step 4：执行操作或等待，然后回到 Step 1**。
   - 记录工具或 LLM 分支结果到 `recent_action`，等待 5 秒，再从 Step 1 重新检查桌面；
     不复用旧的元素 ID 或旧的 inspection。
   - `finish_report` 成功返回会结束 Loop；其他分支继续循环。达到最大迭代次数后，
     必须强制进入 `finish_report` 分支生成最终报告，不直接返回轮次错误。
