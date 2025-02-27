from ai.backend.base_config import CONFIG
import traceback
from ai.backend.util.write_log import logger
from ai.backend.base_config import CONFIG
import re
import ast
import json
from ai.backend.util.token_util import num_tokens_from_messages
import os
import time
from ai.backend.util import base_util
import asyncio


class AIDB:
    def __init__(self, chatClass):
        self.agent_instance_util = chatClass.agent_instance_util
        self.outgoing = chatClass.outgoing
        self.language_mode = chatClass.language_mode
        self.set_language_mode(self.language_mode)
        self.user_name = chatClass.user_name
        self.websocket = chatClass.ws
        self.uid = chatClass.uid

    def set_language_mode(self, language_mode):
        self.language_mode = language_mode

        if self.language_mode == CONFIG.language_english:
            self.error_message_timeout = 'Sorry, this AI-GPT interface call timed out, please try again.'
            self.question_ask = ' This is my question，Answer user questions in English: '
            self.error_miss_data = 'Missing database annotation'
            self.error_miss_key = 'The ApiKey setting is incorrect, please modify it!'
            self.error_no_report_question = 'Sorry, this conversation only deals with report generation issues. Please ask this question in the data analysis conversation.'

        elif self.language_mode == CONFIG.language_chinese:
            self.error_message_timeout = "十分抱歉，本次AI-GPT接口调用超时，请再次重试"
            self.question_ask = ' 以下是我的问题，请用中文回答: '
            self.error_miss_data = '缺少数据库注释'
            self.error_miss_key = "ApiKey设置有误,请修改!"
            self.error_no_report_question = "非常抱歉，本对话只处理报表生成类问题，这个问题请您到数据分析对话中提问"

    async def get_data_desc(self, q_str):
        """Get data description"""
        planner_user = self.agent_instance_util.get_agent_planner_user()
        database_describer = self.agent_instance_util.get_agent_database_describer()

        try:
            qustion_message = "Please explain this data to me."

            if self.language_mode == CONFIG.language_chinese:
                qustion_message = "请为我解释一下这些数据"

            await planner_user.initiate_chat(
                database_describer,
                # message=content + '\n' + " This is my question: " + '\n' + str(qustion_message),
                message=self.agent_instance_util.base_message + '\n' + self.question_ask + '\n' + str(
                    qustion_message),
            )
            answer_message = planner_user.last_message()["content"]
            # print("answer_message: ", answer_message)
        except Exception as e:
            traceback.print_exc()
            logger.error("from user:[{}".format(self.user_name) + "] , " + "error: " + str(e))
            return await self.put_message(500, receiver=CONFIG.talker_bi, data_type=CONFIG.type_comment_first,
                                          content=self.error_message_timeout)

        return await self.put_message(200, receiver=CONFIG.talker_bi, data_type=CONFIG.type_comment_first,
                                      content=answer_message)

    async def check_data_base(self, q_str):
        """Check whether the comments meet the requirements. Those that have passed will not be tested again."""

        message = [
            {
                "role": "system",
                "content": str(q_str),
            }
        ]

        num_tokens = num_tokens_from_messages(message, model='gpt-4')
        print('num_tokens: ', num_tokens)

        if num_tokens < CONFIG.max_token_num:
            table_content = []
            if q_str.get('table_desc'):
                for tb in q_str.get('table_desc'):

                    table_name = tb.get('table_name')
                    table_comment = tb.get('table_comment')
                    if table_comment == '':
                        table_comment = tb.get('table_name')

                    fd_desc = []
                    if tb.get('field_desc'):
                        for fd in tb.get('field_desc'):
                            fd_comment = fd.get('comment')
                            if fd_comment == '':
                                fd_comment = fd.get('name')
                            if fd.get('is_pass') and fd.get('is_pass') == 1:
                                continue
                            else:
                                fd_desc.append({
                                    "name": fd.get('name'),
                                    "comment": fd_comment
                                })

                    if len(fd_desc) > 0:
                        tb_desc = {
                            "table_name": table_name,
                            "table_comment": table_comment,
                            "field_desc": fd_desc
                        }
                        table_content.append(tb_desc)
                    elif tb.get('is_pass') and fd.get('is_pass') == 1:
                        continue
                    else:
                        tb_desc = {
                            "table_name": table_name,
                            "table_comment": table_comment
                        }
                        table_content.append(tb_desc)

            print("The number of tables to be processed this time： ", len(table_content))
            if len(table_content) > 0:
                try:
                    num = 1 + (len(q_str.get('table_desc')) - len(table_content))
                    for db_desc in table_content:
                        print("Start processing table: ", str(db_desc))
                        planner_user = self.agent_instance_util.get_agent_planner_user()
                        database_describer = self.agent_instance_util.get_agent_data_checker_assistant()

                        qustion_message = """Help me check that the following data comments are complete and correct."""

                        if self.language_mode == CONFIG.language_chinese:
                            qustion_message = "帮助我检查下列数据注释是否完整且正确: "


                        await asyncio.wait_for(planner_user.initiate_chat(
                            database_describer,
                            # message=content + '\n' + " This is my question: " + '\n' + str(qustion_message),
                            message=str(qustion_message) + '\n' + str(db_desc),
                        ), timeout=120)  # time out 120 seconds

                        answer_message = planner_user.last_message()["content"]
                        print("answer_message: ", answer_message)

                        match = re.search(
                            r"```.*```", answer_message.strip(), re.MULTILINE | re.IGNORECASE | re.DOTALL
                        )
                        json_str = ""
                        if match:
                            json_str = match.group()
                        else:
                            json_str = answer_message

                        try:
                            json_str = json_str.replace("```json", "")
                            json_str = json_str.replace("```", "")
                            # print('json_str ：', json_str)
                            chart_code_str = json_str.replace("\n", "")
                            if base_util.is_json(chart_code_str):
                                table_desc = json.loads(chart_code_str)
                            else:
                                table_desc = ast.literal_eval(chart_code_str)

                            table_name = table_desc.get('table_name')

                            # print("q_str['table_desc'] ,", q_str['table_desc'])
                            for table in q_str['table_desc']:
                                if table.get('table_name') == table_name:
                                    if table_desc.get('is_pass') and table_desc.get('is_pass') == 1:
                                        if table.get('table_comment') == '':
                                            table['table_comment'] = table.get('table_name')

                                        table['is_pass'] = table_desc.get('is_pass')
                                    if table_desc.get('field_desc'):
                                        for fd in table_desc.get('field_desc'):
                                            field_name = fd.get('name')
                                            for field in table.get('field_desc'):
                                                if field.get('name') == field_name:
                                                    if fd.get('is_pass') and fd.get('is_pass') == 1:
                                                        if field.get('comment') == '':
                                                            field['comment'] = field.get('name')
                                                        field['is_pass'] = fd.get(
                                                            'is_pass')

                            percentage = (num / len(q_str.get('table_desc'))) * 100
                            percentage_integer = int(percentage)

                            await self.put_message(200, CONFIG.talker_log, CONFIG.type_data_check,
                                                   content=percentage_integer)
                            num = num + 1
                        except Exception as e:
                            pass

                except Exception as e:
                    traceback.print_exc()
                    logger.error("from user:[{}".format(self.user_name) + "] , " + "error: " + str(e))
                    await self.put_message(500, CONFIG.talker_log, CONFIG.type_comment, self.error_message_timeout)
                    return

            if q_str.get('table_desc'):
                for tb in q_str.get('table_desc'):
                    if not tb.get('is_pass'):
                        tb['is_pass'] = 0
                    if tb.get('field_desc'):
                        for fd in tb.get('field_desc'):
                            if not fd.get('is_pass'):
                                fd['is_pass'] = 0

            print(" 最终 q_str : ", q_str)
            await self.put_message(200, CONFIG.talker_bi, CONFIG.type_comment, q_str)
        else:
            if self.language_mode == CONFIG.language_chinese:
                content = '所选表格' + str(num_tokens) + ' , 超过了最大长度:' + str(CONFIG.max_token_num) + ' , 请重新选择'
            else:
                content = 'The selected table length ' + str(num_tokens) + ' ,  exceeds the maximum length: ' + str(
                    CONFIG.max_token_num) + ' , please select again'
            return await self.put_message(500, CONFIG.talker_log, CONFIG.type_data_check, content)

    async def put_message(self, state=200, receiver='log', data_type=None, content=None):
        mess = {'state': state, 'data': {'data_type': data_type, 'content': content}, 'receiver': receiver}
        consume_output = json.dumps(mess)
        # await self.outgoing.put(consume_output)
        # await self.ws.send(consume_output)
        await asyncio.wait_for(self.websocket.send(consume_output), timeout=CONFIG.request_timeout)

        print(str(time.strftime("%Y-%m-%d %H:%M:%S",
                                time.localtime())) + ' ---- ' + "from user:[{}".format(
            self.user_name) + "], reply a message:{}".format(consume_output))

    async def check_api_key(self):
        self.agent_instance_util.api_key_use = True

        # .token_[uid].json
        token_path = CONFIG.up_file_path + '.token_' + str(self.uid) + '.json'
        if os.path.exists(token_path):
            try:
                with open(token_path, 'r') as file:
                    data = json.load(file)

                OpenaiApiKey = data['OpenaiApiKey']
                print('OpenaiApiKey : ', OpenaiApiKey)

                self.agent_instance_util.set_api_key(OpenaiApiKey)

                HttpProxyHost = data['HttpProxyHost']
                HttpProxyPort = data['HttpProxyPort']

                if HttpProxyHost is not None and len(str(HttpProxyHost)) > 0 and HttpProxyPort is not None and len(
                        str(HttpProxyPort)) > 0:
                    # openai_proxy = "http://127.0.0.1:7890"
                    self.agent_instance_util.openai_proxy = 'http://' + str(HttpProxyHost) + ':' + str(HttpProxyPort)


                planner_user = self.agent_instance_util.get_agent_planner_user(is_log_out=False)
                api_check = self.agent_instance_util.get_agent_api_check()
                await asyncio.wait_for(planner_user.initiate_chat(
                    api_check,
                    # message=content + '\n' + " This is my question: " + '\n' + str(qustion_message),
                    message=""" 5-2 =?? """,
                ), timeout=120)  # time out 120 seconds


                self.agent_instance_util.api_key_use = True


                return True
            except Exception as e:
                traceback.print_exc()
                logger.error("from user:[{}".format(self.user_name) + "] , " + "error: " + str(e))
                await self.put_message(500, CONFIG.talker_log, CONFIG.type_log_data, self.error_miss_key)
                return False


        else:
            await self.put_message(500, receiver=CONFIG.talker_log, data_type=CONFIG.type_log_data,
                                   content=self.error_miss_key)
            return False


    async def test_api_key(self):
        self.agent_instance_util.api_key_use = True

        # .token_[uid].json
        token_path = CONFIG.up_file_path + '.token_' + str(self.uid) + '.json'
        if os.path.exists(token_path):
            try:
                with open(token_path, 'r') as file:
                    data = json.load(file)

                OpenaiApiKey = data['OpenaiApiKey']
                print('OpenaiApiKey : ', OpenaiApiKey)

                self.agent_instance_util.set_api_key(OpenaiApiKey)

                HttpProxyHost = data['HttpProxyHost']
                print('HttpProxyHost : ', HttpProxyHost)
                HttpProxyPort = data['HttpProxyPort']
                print('HttpProxyPort : ', HttpProxyPort)

                if HttpProxyHost is not None and len(str(HttpProxyHost)) > 0 and HttpProxyPort is not None and len(
                        str(HttpProxyPort)) > 0:
                    # openai_proxy = "http://127.0.0.1:7890"
                    self.agent_instance_util.openai_proxy = 'http://' + str(HttpProxyHost) + ':' + str(HttpProxyPort)


                planner_user = self.agent_instance_util.get_agent_planner_user(is_log_out=False)
                api_check = self.agent_instance_util.get_agent_api_check()
                await asyncio.wait_for(planner_user.initiate_chat(
                    api_check,
                    # message=content + '\n' + " This is my question: " + '\n' + str(qustion_message),
                    message=""" 5-2 =?? """,
                ), timeout=120)  # time out 120 seconds

                self.agent_instance_util.api_key_use = True

                if self.language_mode == CONFIG.language_chinese:
                    return await self.put_message(200, CONFIG.talker_api, CONFIG.type_test, '检测通过')
                else:
                    return await self.put_message(200, CONFIG.talker_api, CONFIG.type_test, 'test success')



            except Exception as e:
                traceback.print_exc()
                logger.error("from user:[{}".format(self.user_name) + "] , " + "error: " + str(e))

                if self.language_mode == CONFIG.language_chinese:
                    return await self.put_message(200, CONFIG.talker_api, CONFIG.type_test, '检测未通过...')
                else:
                    return await self.put_message(200, CONFIG.talker_api, CONFIG.type_test, 'test fail')

        else:
            if self.language_mode == CONFIG.language_chinese:
                return await self.put_message(200, CONFIG.talker_api, CONFIG.type_test, '未检测到apikey,请先保存')
            else:
                return await self.put_message(200, CONFIG.talker_api, CONFIG.type_test, 'apikey not detected, please save first')
