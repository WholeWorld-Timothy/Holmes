from ai.backend.base_config import CONFIG
from ai.backend.aidb import AIDB
from ai.agents.agentchat import HumanProxyAgent, TaskSelectorAgent


class Report(AIDB):
    def get_agent_user_proxy(self):
        """ Human Proxy  """
        user_proxy = HumanProxyAgent(
            name="Admin",
            system_message="A human admin. Interact with the planner to discuss the plan. ",
            code_execution_config={"last_n_messages": 1, "work_dir": "paper"},
            human_input_mode="NEVER",
            websocket=self.websocket,
            user_name=self.user_name,
            function_map={
                "task_generate_report": self.task_generate_report,
                "task_base": self.task_base,
            },
            outgoing=self.outgoing,
        )
        return user_proxy

    def get_agent_select_report_assistant(self):
        """select_report_assistant"""
        select_report_assistant = TaskSelectorAgent(
            name="select_report_assistant",
            system_message="""You are a helpful AI assistant.
                     Divide the questions raised by users into corresponding task types.
                     Different tasks have different processing methods.
                     Task types are generally divided into the following categories:
                     - Report generation task: query data, and finally display the data in the form of charts.
                     - base tasks: analyze existing data and draw conclusions about the given problem.

                 Reply "TERMINATE" in the end when everything is done.
                      """ + '\n' + self.agent_instance_util.base_mysql_info,
            human_input_mode="NEVER",
            user_name=self.user_name,
            websocket=self.websocket,
            llm_config={
                "functions": [
                    {
                        "name": "task_generate_report",
                        "description": """chart generation task, The user ask that the data be finally displayed in the form of a chart.If the question does not clearly state that a  chart is to be generated, it does not belong to this task.""",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "qustion_message": {
                                    "type": "string",
                                    "description": "Task content",
                                }
                            },
                            "required": ["qustion_message"],
                        },
                    },
                    {
                        "name": "task_base",
                        "description": "Processing a task ",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "qustion_message": {
                                    "type": "string",
                                    "description": "Task content",
                                }
                            },
                            "required": ["qustion_message"],
                        },
                    },
                ],
                "config_list": self.agent_instance_util.config_list_gpt4_turbo,
                "request_timeout": CONFIG.request_timeout,
            },
            openai_proxy=self.agent_instance_util.openai_proxy,
        )
        return select_report_assistant

    async def start_chatgroup(self, q_str):
        user_proxy = self.get_agent_user_proxy()
        base_mysql_assistant = self.get_agent_select_report_assistant()

        await user_proxy.initiate_chat(
            base_mysql_assistant,
            message=self.agent_instance_util.base_message + '\n' + self.question_ask + '\n' + str(q_str),
        )


    async def task_base(self, qustion_message):
        """ Task type: base question """
        return self.error_no_report_question


    async def task_generate_report(self, qustion_message):
        return self.qustion_message
