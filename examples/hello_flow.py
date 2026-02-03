import pyoco


def build_flow(name: str = "main") -> pyoco.Flow:
    @pyoco.task
    def hello():
        print("hello from a distributed worker")
        return "hello"

    @pyoco.task
    def world(ctx):
        msg = ctx.results["hello"]
        print(f"world got: {msg}")
        return "world"

    flow = pyoco.Flow(name=name)
    flow.add_task(hello.task)
    flow.add_task(world.task)
    world.task.dependencies.add(hello.task)
    hello.task.dependents.add(world.task)
    return flow


def resolve_flow(flow_name: str) -> pyoco.Flow:
    if flow_name != "main":
        raise KeyError(flow_name)
    return build_flow(flow_name)

