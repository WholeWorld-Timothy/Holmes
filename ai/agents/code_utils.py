import signal
import subprocess
import sys
import os
import pathlib
from typing import List, Dict, Tuple, Optional, Union, Callable
import re
import time
from hashlib import md5
import logging
from ai.agents import oai
import json
import traceback
from ai.backend.base_config import if_hide_sensitive

try:
    import docker
except ImportError:
    docker = None

DEFAULT_MODEL = "gpt-4"
FAST_MODEL = "gpt-3.5-turbo"
# Regular expression for finding a code block
CODE_BLOCK_PATTERN = r"```(\w*)\n(.*?)\n```"
WORKING_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "extensions")
UNKNOWN = "unknown"
TIMEOUT_MSG = "Timeout"
DEFAULT_TIMEOUT = 600
WIN32 = sys.platform == "win32"
PATH_SEPARATOR = WIN32 and "\\" or "/"

logger = logging.getLogger(__name__)


def infer_lang(code):
    """infer the language for the code.
    TODO: make it robust.
    """
    if code.startswith("python ") or code.startswith("pip") or code.startswith("python3 "):
        return "sh"

    # check if code is a valid python code
    try:
        compile(code, "test", "exec")
        return "python"
    except SyntaxError:
        # not a valid python code
        return UNKNOWN


def extract_code(
        text: str, pattern: str = CODE_BLOCK_PATTERN, detect_single_line_code: bool = False
) -> List[Tuple[str, str]]:
    """Extract code from a text.

    Args:
        text (str): The text to extract code from.
        pattern (str, optional): The regular expression pattern for finding the
            code block. Defaults to CODE_BLOCK_PATTERN.
        detect_single_line_code (bool, optional): Enable the new feature for
            extracting single line code. Defaults to False.

    Returns:
        list: A list of tuples, each containing the language and the code.
          If there is no code block in the input text, the language would be "unknown".
          If there is code block but the language is not specified, the language would be "".
    """
    if not detect_single_line_code:
        match = re.findall(pattern, text, flags=re.DOTALL)
        return match if match else [(UNKNOWN, text)]

    # Extract both multi-line and single-line code block, separated by the | operator
    # `{3}(\w+)?\s*([\s\S]*?)`{3}: Matches multi-line code blocks.
    #    The (\w+)? matches the language, where the ? indicates it is optional.
    # `([^`]+)`: Matches inline code.
    code_pattern = re.compile(r"`{3}(\w+)?\s*([\s\S]*?)`{3}|`([^`]+)`")
    code_blocks = code_pattern.findall(text)

    # Extract the individual code blocks and languages from the matched groups
    extracted = []
    for lang, group1, group2 in code_blocks:
        if group1:
            extracted.append((lang.strip(), group1.strip()))
        elif group2:
            extracted.append(("", group2.strip()))

    return extracted


# _FIND_CODE_SYS_MSG = [
#     {
#         "role": "system",
#         "content": """In the following conversation, an assistant suggests code and a user is expected to run it.
# Read the conversation, and then find all the right code blocks for the user to run next in the right order.
# Only return the code blocks that are expected to run.
# Don't include code blocks which have been executed unless the user is requested to run the same block again.
# When the user needs to run multiple blocks in sequence, make sure to output all the blocks to run in a right order.
# If the line beginning with "# filename" is put before a code block, move it into the code block as the first line.
# Make sure to add the right "python" or "sh" identifier if the language identifier is missing for a code block.
# Don't make other changes to the code blocks.
# Don't reply anything else if at least one code block is expected to run.
# If no code block is expeted to run, check whether the task has been successfully finished at full satisfaction.
# If not, reply with the reason why the task is not finished.""",
#     },
# ]
# _FIND_CODE_CONFIG = {
#     "model": FAST_MODEL,
# }


# def find_code(messages: List[Dict], sys_msg=None, **config) -> Tuple[List[Tuple[str, str]], str]:
#     """Find code from a list of messages.

#     Args:
#         messages (str): The list of messages to find code from.
#         sys_msg (Optional, str): The system message to prepend to the messages.
#         config (Optional, dict): The configuration for the API call.

#     Returns:
#         list: A list of tuples, each containing the language and the code.
#         str: The generated text by llm.
#     """
#     params = {**_FIND_CODE_CONFIG, **config}
#     if sys_msg is None or not sys_msg[0]["content"]:
#         sys_msg = _FIND_CODE_SYS_MSG
#     response = oai.ChatCompletion.create(messages=sys_msg + messages, **params)
#     content = oai.Completion.extract_text(response)[0]
#     return extract_code(content), content


def generate_code(pattern: str = CODE_BLOCK_PATTERN, **config) -> Tuple[str, float]:
    """Generate code.

    Args:
        pattern (Optional, str): The regular expression pattern for finding the code block.
            The default pattern is for finding a code block in a markdown file.
        config (Optional, dict): The configuration for the API call.

    Returns:
        str: The generated code.
        float: The cost of the generation.
    """
    response = oai.Completion.create(**config)
    return extract_code(oai.Completion.extract_text(response)[0], pattern), response["cost"]


_IMPROVE_FUNCTION_CONFIG = {
    "prompt": """Improve the function '{func_name}' to achieve the objective '{objective}'.
The current implementation of the function is as follows:
{file_string}""",
    "model": DEFAULT_MODEL,
    "request_timeout": 600,
}


def improve_function(file_name, func_name, objective, **config):
    """(work in progress) Improve the function to achieve the objective."""
    params = {**_IMPROVE_FUNCTION_CONFIG, **config}
    # read the entire file into a str
    with open(file_name, "r") as f:
        file_string = f.read()
    response = oai.Completion.create(
        {"func_name": func_name, "objective": objective, "file_string": file_string}, **params
    )
    return oai.Completion.extract_text(response)[0], response["cost"]


_IMPROVE_CODE_CONFIG = {
    "prompt": """Analyze the code in the following files and return a list of suggestions for improvement{followup}, to achieve the objective of '{objective}'.
{code}
""",
    "model": DEFAULT_MODEL,
    "request_timeout": 900,
}


def improve_code(files, objective, suggest_only=True, **config):
    """Improve the code to achieve a given objective.

    Args:
        files (list): A list of file names containing the source code.
        objective (str): The objective to achieve.
        suggest_only (bool): Whether to return only the suggestions or the improved code.
        config (Optional, dict): The configuration for the API call.

    Returns:
        str: The improved code if suggest_only=False; a list of suggestions if suggest_only=True (default).
        float: The cost of the generation.
    """
    code = ""
    for file_name in files:
        # read the entire file into a string
        with open(file_name, "r") as f:
            file_string = f.read()
        code += f"""{file_name}:
{file_string}

"""
    params = {**_IMPROVE_CODE_CONFIG, **config}
    followup = "" if suggest_only else " followed by the improved code"
    response = oai.Completion.create({"objective": objective, "code": code, "followup": followup}, **params)
    return oai.Completion.extract_text(response)[0], response["cost"]


def timeout_handler(signum, frame):
    raise TimeoutError("Timed out!")


def _cmd(lang):
    if lang.startswith("python") or lang in ["bash", "sh", "powershell"]:
        return lang
    if lang in ["shell"]:
        return "sh"
    if lang in ["ps1"]:
        return "powershell"
    raise NotImplementedError(f"{lang} not recognized in code execution")


def execute_code(
        code: Optional[str] = None,
        timeout: Optional[int] = None,
        filename: Optional[str] = None,
        work_dir: Optional[str] = None,
        use_docker: Optional[Union[List[str], str, bool]] = True,
        lang: Optional[str] = "python",
) -> Tuple[int, str, str]:
    """Execute code in a docker container.
    This function is not tested on MacOS.

    Args:
        code (Optional, str): The code to execute.
            If None, the code from the file specified by filename will be executed.
            Either code or filename must be provided.
        timeout (Optional, int): The maximum execution time in seconds.
            If None, a default timeout will be used. The default timeout is 600 seconds. On Windows, the timeout is not enforced when use_docker=False.
        filename (Optional, str): The file name to save the code or where the code is stored when `code` is None.
            If None, a file with a randomly generated name will be created.
            The randomly generated file will be deleted after execution.
            The file name must be a relative path. Relative paths are relative to the working directory.
        work_dir (Optional, str): The working directory for the code execution.
            If None, a default working directory will be used.
            The default working directory is the "extensions" directory under
            "path_to_autogen".
        use_docker (Optional, list, str or bool): The docker image to use for code execution.
            If a list or a str of image name(s) is provided, the code will be executed in a docker container
            with the first image successfully pulled.
            If None, False or empty, the code will be executed in the current environment.
            Default is True, which will be converted into a list.
            If the code is executed in the current environment,
            the code must be trusted.
        lang (Optional, str): The language of the code. Default is "python".

    Returns:
        int: 0 if the code executes successfully.
        str: The error message if the code fails to execute; the stdout otherwise.
        image: The docker image name after container run when docker is used.
    """
    if all((code is None, filename is None)):
        error_msg = f"Either {code=} or {filename=} must be provided."
        logger.error(error_msg)
        raise AssertionError(error_msg)

    # Warn if docker was requested but cannot be provided. In this case
    # the current behavior is to fall back to run natively, but this behavior
    # is subject to change.
    if use_docker and docker is None:
        use_docker = False
        logger.warning(
            "execute_code was called with use_docker evaluating to True, but the python docker package is not available. Falling back to native code execution. Note: this fallback behavior is subject to change"
        )

    timeout = timeout or DEFAULT_TIMEOUT
    original_filename = filename
    if WIN32 and lang in ["sh", "shell"] and (not use_docker):
        lang = "ps1"
    if filename is None:
        code_hash = md5(code.encode()).hexdigest()
        # create a file with a automatically generated name
        filename = f"tmp_code_{code_hash}.{'py' if lang.startswith('python') else lang}"
    if work_dir is None:
        work_dir = WORKING_DIR
    filepath = os.path.join(work_dir, filename)
    file_dir = os.path.dirname(filepath)
    os.makedirs(file_dir, exist_ok=True)
    if code is not None:
        with open(filepath, "w", encoding="utf-8") as fout:
            fout.write(code)
    # check if already running in a docker container
    in_docker_container = os.path.exists("/.dockerenv")
    if not use_docker or in_docker_container:
        # already running in a docker container
        cmd = [
            sys.executable if lang.startswith("python") else _cmd(lang),
            f".\\{filename}" if WIN32 else filename,
        ]
        if WIN32:
            logger.warning("SIGALRM is not supported on Windows. No timeout will be enforced.")
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
            )
        else:
            signal.signal(signal.SIGALRM, timeout_handler)
            try:
                signal.alarm(timeout)
                # run the code in a subprocess in the current docker container in the working directory
                result = subprocess.run(
                    cmd,
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                )
                signal.alarm(0)
            except TimeoutError:
                if original_filename is None:
                    os.remove(filepath)
                return 1, TIMEOUT_MSG, None
        if original_filename is None:
            os.remove(filepath)
        if result.returncode:
            logs = result.stderr
            if original_filename is None:
                abs_path = str(pathlib.Path(filepath).absolute())
                logs = logs.replace(str(abs_path), "").replace(filename, "")
            else:
                abs_path = str(pathlib.Path(work_dir).absolute()) + PATH_SEPARATOR
                logs = logs.replace(str(abs_path), "")
        else:
            logs = result.stdout
        return result.returncode, logs, None

    # create a docker client
    client = docker.from_env()
    image_list = (
        ["python:3-alpine", "python:3", "python:3-windowsservercore"]
        if use_docker is True
        else [use_docker]
        if isinstance(use_docker, str)
        else use_docker
    )
    for image in image_list:
        # check if the image exists
        try:
            client.images.get(image)
            break
        except docker.errors.ImageNotFound:
            # pull the image
            print("Pulling image", image)
            try:
                client.images.pull(image)
                break
            except docker.errors.DockerException:
                print("Failed to pull image", image)
    # get a randomized str based on current time to wrap the exit code
    exit_code_str = f"exitcode{time.time()}"
    abs_path = pathlib.Path(work_dir).absolute()
    cmd = [
        "sh",
        "-c",
        f"{_cmd(lang)} {filename}; exit_code=$?; echo -n {exit_code_str}; echo -n $exit_code; echo {exit_code_str}",
    ]
    # create a docker container
    container = client.containers.run(
        image,
        command=cmd,
        working_dir="/workspace",
        detach=True,
        # get absolute path to the working directory
        volumes={abs_path: {"bind": "/workspace", "mode": "rw"}},
    )
    start_time = time.time()
    while container.status != "exited" and time.time() - start_time < timeout:
        # Reload the container object
        container.reload()
    if container.status != "exited":
        container.stop()
        container.remove()
        if original_filename is None:
            os.remove(filepath)
        return 1, TIMEOUT_MSG, image
    # get the container logs
    logs = container.logs().decode("utf-8").rstrip()
    # commit the image
    tag = filename.replace("/", "")
    container.commit(repository="python", tag=tag)
    # remove the container
    container.remove()
    # check if the code executed successfully
    exit_code = container.attrs["State"]["ExitCode"]
    if exit_code == 0:
        # extract the exit code from the logs
        pattern = re.compile(f"{exit_code_str}(\\d+){exit_code_str}")
        match = pattern.search(logs)
        exit_code = 1 if match is None else int(match.group(1))
        # remove the exit code from the logs
        logs = logs if match is None else pattern.sub("", logs)

    if original_filename is None:
        os.remove(filepath)
    if exit_code:
        logs = logs.replace(f"/workspace/{filename if original_filename is None else ''}", "")
    # return the exit code, logs and image
    return exit_code, logs, f"python:{tag}"


_GENERATE_ASSERTIONS_CONFIG = {
    "prompt": """Given the signature and docstring, write the exactly same number of assertion(s) for the provided example(s) in the docstring, without assertion messages.

func signature:
{definition}
assertions:""",
    "model": FAST_MODEL,
    "max_tokens": 256,
    "stop": "\n\n",
}


def generate_assertions(definition: str, **config) -> Tuple[str, float]:
    """Generate assertions for a function.

    Args:
        definition (str): The function definition, including the signature and docstr.
        config (Optional, dict): The configuration for the API call.

    Returns:
        str: The generated assertions.
        float: The cost of the generation.
    """
    params = {**_GENERATE_ASSERTIONS_CONFIG, **config}
    response = oai.Completion.create(
        {"definition": definition},
        **params,
    )
    assertions = oai.Completion.extract_text(response)[0]
    return assertions, response["cost"]


def _remove_check(response):
    """Remove the check function from the response."""
    # find the position of the check function
    pos = response.find("def check(")
    if pos == -1:
        return response
    return response[:pos]


def eval_function_completions(
        responses: List[str],
        definition: str,
        test: Optional[str] = None,
        entry_point: Optional[str] = None,
        assertions: Optional[Union[str, Callable[[str], Tuple[str, float]]]] = None,
        timeout: Optional[float] = 3,
        use_docker: Optional[bool] = True,
) -> Dict:
    """Select a response from a list of responses for the function completion task (using generated assertions), and/or evaluate if the task is successful using a gold test.

    Args:
        responses (list): The list of responses.
        definition (str): The input definition.
        test (Optional, str): The test code.
        entry_point (Optional, str): The name of the function.
        assertions (Optional, str or Callable): The assertion code which serves as a filter of the responses, or an assertion generator.
            When provided, only the responses that pass the assertions will be considered for the actual test (if provided).
        timeout (Optional, float): The timeout for executing the code.

    Returns:
        dict: The success metrics.
    """
    n = len(responses)
    if assertions is None:
        # no assertion filter
        success_list = []
        for i in range(n):
            response = _remove_check(responses[i])
            code = (
                f"{response}\n{test}\ncheck({entry_point})"
                if response.startswith("def")
                else f"{definition}{response}\n{test}\ncheck({entry_point})"
            )
            success = execute_code(code, timeout=timeout, use_docker=use_docker)[0] == 0
            success_list.append(success)
        return {
            "expected_success": 1 - pow(1 - sum(success_list) / n, n),
            "success": any(s for s in success_list),
        }
    if callable(assertions) and n > 1:
        # assertion generator
        assertions, gen_cost = assertions(definition)
    else:
        assertions, gen_cost = None, 0
    if n > 1 or test is None:
        for i in range(n):
            response = responses[i] = _remove_check(responses[i])
            code = (
                f"{response}\n{assertions}" if response.startswith("def") else f"{definition}{response}\n{assertions}"
            )
            succeed_assertions = execute_code(code, timeout=timeout, use_docker=use_docker)[0] == 0
            if succeed_assertions:
                break
    else:
        # just test, no need to check assertions
        succeed_assertions = False
        i, response = 0, responses[0]
    if test is None:
        # no test code
        return {
            "index_selected": i,
            "succeed_assertions": succeed_assertions,
            "gen_cost": gen_cost,
            "assertions": assertions,
        }
    code_test = (
        f"{response}\n{test}\ncheck({entry_point})"
        if response.startswith("def")
        else f"{definition}{response}\n{test}\ncheck({entry_point})"
    )
    success = execute_code(code_test, timeout=timeout, use_docker=use_docker)[0] == 0
    return {
        "index_selected": i,
        "succeed_assertions": succeed_assertions,
        "success": success,
        "gen_cost": gen_cost,
        "assertions": assertions,
    }


_FUNC_COMPLETION_PROMPT = "# Python 3{definition}"
_FUNC_COMPLETION_STOP = ["\nclass", "\ndef", "\nif", "\nprint"]
_IMPLEMENT_CONFIGS = [
    {"model": FAST_MODEL, "prompt": _FUNC_COMPLETION_PROMPT, "temperature": 0, "seed": 0},
    {"model": FAST_MODEL, "prompt": _FUNC_COMPLETION_PROMPT, "stop": _FUNC_COMPLETION_STOP, "n": 7, "seed": 0},
    {"model": DEFAULT_MODEL, "prompt": _FUNC_COMPLETION_PROMPT, "temperature": 0, "seed": 1},
    {"model": DEFAULT_MODEL, "prompt": _FUNC_COMPLETION_PROMPT, "stop": _FUNC_COMPLETION_STOP, "n": 2, "seed": 2},
    {"model": DEFAULT_MODEL, "prompt": _FUNC_COMPLETION_PROMPT, "stop": _FUNC_COMPLETION_STOP, "n": 1, "seed": 2},
]


class PassAssertionFilter:
    def __init__(self, assertions):
        self._assertions = assertions
        self.cost = 0
        self.metrics = self.responses = None

    def pass_assertions(self, context, response, **_):
        """Check if the response passes the assertions."""
        responses = oai.Completion.extract_text(response)
        metrics = eval_function_completions(responses, context["definition"], assertions=self._assertions)
        self._assertions = metrics["assertions"]
        self.cost += metrics["gen_cost"]
        self.metrics = metrics
        self.responses = responses
        return metrics["succeed_assertions"]


def implement(
        definition: str,
        configs: Optional[List[Dict]] = None,
        assertions: Optional[Union[str, Callable[[str], Tuple[str, float]]]] = generate_assertions,
) -> Tuple[str, float]:
    """Implement a function from a definition.

    Args:
        definition (str): The function definition, including the signature and docstr.
        configs (list): The list of configurations for completion.
        assertions (Optional, str or Callable): The assertion code which serves as a filter of the responses, or an assertion generator.

    Returns:
        str: The implementation.
        float: The cost of the implementation.
        int: The index of the configuration which generates the implementation.
    """
    cost = 0
    configs = configs or _IMPLEMENT_CONFIGS
    if len(configs) > 1 and callable(assertions):
        assertions, cost = assertions(definition)
    assertion_filter = PassAssertionFilter(assertions)
    response = oai.Completion.create(
        {"definition": definition}, config_list=configs, filter_func=assertion_filter.pass_assertions
    )
    cost += assertion_filter.cost + response["cost"]
    return assertion_filter.responses[assertion_filter.metrics["index_selected"]], cost, response["config_id"]

    # for i, config in enumerate(configs):
    #     response = oai.Completion.create({"definition": definition}, **config)
    #     cost += oai.Completion.cost(response)
    #     responses = oai.Completion.extract_text(response)
    #     metrics = eval_function_completions(responses, definition, assertions=assertions)
    #     assertions = metrics["assertions"]
    #     cost += metrics["gen_cost"]
    #     if metrics["succeed_assertions"] or i == len(configs) - 1:
    #         return responses[metrics["index_selected"]], cost, i


async def tell_logger(websocket, log_str):
    try:
        log_str = str(log_str)
        if if_hide_sensitive:
            # Replace hidden python code blocks to prevent private information from being exposed in logs
            CODE_BLOCK_PATTERN = r"```(\w*)\n(.*?)\n```"
            match = re.findall(CODE_BLOCK_PATTERN, log_str, flags=re.DOTALL)
            if len(match) > 0 and match[0][0] == 'python':
                replacement = """
                               ```python
                               ******* python code ************
                               ******* python code ************
                               ******* python code ************

                               ```
                                   """
                log_str = re.sub(CODE_BLOCK_PATTERN, replacement, log_str, flags=re.DOTALL)
                # print("new_text :", new_text)

        result_message = {
            'state': 200,
            'receiver': 'log',
            'data': {
                'data_type': 'log_data',
                'content': log_str
            }
        }

        send_json_str = json.dumps(result_message)
        await websocket.send(send_json_str)

    except Exception as e:
        traceback.print_exc()
        logger.error(str(e))

