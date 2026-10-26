import os
from spacetime import Node
from utils.pcc_models import Register

def init(df, user_agent, fresh):
    print("DEBUG: Reading registration", flush=True)
    reg = df.read_one(Register, user_agent)
    print("DEBUG: Registration read completed", flush=True)

    if not reg:
        print("DEBUG: Creating registration", flush=True)
        reg = Register(user_agent, fresh)
        df.add_one(Register, reg)
        df.commit()
        print("DEBUG: Pushing registration", flush=True)
        df.push_await()
        print("DEBUG: Registration push completed", flush=True)

    while not reg.load_balancer:
        print("DEBUG: Waiting for load balancer", flush=True)
        df.pull_await()
        print("DEBUG: Server update received", flush=True)

        if reg.invalid:
            raise RuntimeError("User agent string is not acceptable.")

        if reg.load_balancer:
            df.delete_one(Register, reg)
            df.commit()
            df.push()

    return reg.load_balancer
def get_cache_server(config, restart):
    init_node = Node(
        init, Types=[Register], dataframe=(config.host, config.port))
    return init_node.start(
        config.user_agent, restart or not os.path.exists(config.save_file))
