"""C 模块测试样例。

用于验证核验、合规、导出功能。
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.compliance import compliance_check
from agent.contracts import Draft, Fact, ImageRef, Report
from agent.export import export_markdown, export_text
from agent.verify import verify


def test_verify():
    """测试事实核验。"""
    print("=" * 60)
    print("测试 1：事实核验")
    print("=" * 60)

    # 构造测试数据
    facts = [
        Fact(
            fact_id="f1",
            model="MateBook D 14",
            field="屏幕.尺寸",
            value="14 英寸",
            qualifier="",
            source_title="产品事实.md",
            source_path="P1/02-MateBook-Windows/MateBook D 14/产品事实.md",
            review_status="ok"
        ),
        Fact(
            fact_id="f2",
            model="MateBook D 14",
            field="电池.容量",
            value="56 Wh",
            qualifier="标准版",
            source_title="产品事实.md",
            source_path="P1/02-MateBook-Windows/MateBook D 14/产品事实.md",
            review_status="ok"
        ),
        Fact(
            fact_id="f3",
            model="MateBook D 14",
            field="尺寸与重量.重量",
            value="约 1.39 kg",
            qualifier="",
            source_title="产品事实.md",
            source_path="P1/02-MateBook-Windows/MateBook D 14/产品事实.md",
            review_status="pending_review",
            review_note="标签与数值可能错位,待复核"
        ),
    ]

    images = [
        ImageRef(
            filename="hwpc_matebook-d-14-2024_高清护眼屏幕_01.png",
            model="MateBook D 14",
            source="官网图片 / P1 图片索引",
            caption="高清护眼屏幕",
            suggested_position="屏幕介绍段落"
        )
    ]

    # 测试案例 1：正常草稿
    draft1 = Draft(
        title="MateBook D 14：学生党的轻薄本首选",
        lead="14 英寸大屏，轻至 1.39kg",
        body="屏幕尺寸为 14 英寸，电池容量 56 Wh（标准版），适合日常使用。",
        image_plan=[images[0]],
        call_to_action="了解更多",
        used_fact_ids=["f1", "f2"]
    )

    report1 = verify(draft1, facts, images)
    print(f"\n案例 1 - 正常草稿:")
    print(f"阻断: {report1.blocked}")
    print(f"事实核验: {len(report1.fact_check)} 项")
    print(f"图片核验: {len(report1.image_check)} 项")

    # 测试案例 2：缺失限定条件
    draft2 = Draft(
        title="MateBook D 14",
        lead="",
        body="电池容量 56 Wh，长续航。",  # 缺少"标准版"限定
        image_plan=[images[0]],
        call_to_action="",
        used_fact_ids=["f2"]
    )

    report2 = verify(draft2, facts, images)
    print(f"\n案例 2 - 缺失限定条件:")
    print(f"阻断: {report2.blocked}")
    for item in report2.fact_check:
        if item.get("status") == "failed":
            print(f"- 失败: {item.get('issue')}")

    # 测试案例 3：使用待复核字段
    draft3 = Draft(
        title="MateBook D 14",
        lead="",
        body="重量约 1.39 kg，轻薄便携。",
        image_plan=[],
        call_to_action="",
        used_fact_ids=["f3"]
    )

    report3 = verify(draft3, facts, images)
    print(f"\n案例 3 - 使用待复核字段:")
    print(f"待确认项: {len(report3.to_confirm)} 项")
    for item in report3.to_confirm:
        print(f"- {item}")


def test_compliance():
    """测试合规检查。"""
    print("\n" + "=" * 60)
    print("测试 2：合规检查")
    print("=" * 60)

    # 测试案例 1：包含禁用词
    draft1 = Draft(
        title="全网最低价！MateBook D 14 最后三台",
        lead="唯一的选择，碾压竞品",
        body="国补立减 500 元，亲测好用，用户评价五星。",
        image_plan=[],
        call_to_action="懂的私聊",
        tags=["最强", "第一"]
    )

    results1 = compliance_check(draft1)
    print(f"\n案例 1 - 包含多个禁用词:")
    print(f"合规问题: {len(results1)} 项")
    blocking = sum(1 for item in results1 if item.get("blocking"))
    print(f"阻断项: {blocking}")

    for item in results1[:5]:  # 显示前5项
        emoji = "🚫" if item.get("blocking") else "⚠️"
        print(f"{emoji} {item.get('category')}: {item.get('term')}")

    # 测试案例 2：正常内容
    draft2 = Draft(
        title="MateBook D 14：适合学生使用的轻薄本",
        lead="14 英寸屏幕，便携设计",
        body="搭载高性能处理器，适合日常办公和学习使用。",
        image_plan=[],
        call_to_action="访问官网了解详情",
        tags=["轻薄", "学生"]
    )

    results2 = compliance_check(draft2)
    print(f"\n案例 2 - 正常内容:")
    print(f"合规问题: {len(results2)} 项")


def test_export():
    """测试导出功能。"""
    print("\n" + "=" * 60)
    print("测试 3：导出功能")
    print("=" * 60)

    draft = Draft(
        title="MateBook D 14：学生党的轻薄本首选",
        lead="14 英寸大屏，轻至 1.39kg",
        body="MateBook D 14 搭载 14 英寸高清屏幕，支持护眼模式。\n\n"
             "电池容量 56 Wh（标准版），满足全天使用需求。\n\n"
             "轻薄设计，重量约 1.39kg，方便携带。",
        image_plan=[
            ImageRef(
                filename="hwpc_matebook-d-14-2024_高清护眼屏幕_01.png",
                model="MateBook D 14",
                source="官网图片",
                caption="高清护眼屏幕",
                suggested_position="屏幕介绍"
            )
        ],
        call_to_action="访问华为官网了解更多",
        tags=["轻薄本", "学生", "14英寸"],
        used_fact_ids=["f1", "f2"]
    )

    report = Report(
        fact_check=[{"type": "overall", "status": "passed", "message": "事实核验通过"}],
        image_check=[{"type": "overall", "status": "passed", "message": "图片核验通过"}],
        compliance=[],
        to_confirm=[],
        blocked=False
    )

    # 导出 Markdown
    markdown = export_markdown(draft, report)
    print("\nMarkdown 导出（前 500 字符）:")
    print(markdown[:500])
    print("...")

    # 导出纯文本
    text = export_text(draft, report)
    print("\n纯文本导出（前 300 字符）:")
    print(text[:300])
    print("...")


def main():
    """运行全部测试。"""
    print("\n🧪 C 模块功能测试\n")

    try:
        test_verify()
        test_compliance()
        test_export()

        print("\n" + "=" * 60)
        print("✅ 测试完成！")
        print("=" * 60)
        print("\n提示：")
        print("1. 以上为简化测试，完整测试需要 B 完成 compose 后联调")
        print("2. 运行界面：py app.py")
        print("3. 详细说明见 docs/handoff.md")

    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
