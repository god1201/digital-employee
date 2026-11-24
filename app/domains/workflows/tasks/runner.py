from app.domains.workflows.tasks.engine import run_task_graph


async def run_task_instance(instance_id: int, start_index: int = 0) -> None:
    """后台任务入口，供 FastAPI BackgroundTasks 调用。"""
    await run_task_graph(instance_id, start_index=start_index)
