#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

from typing import Any, Callable, Sequence, NewType, Dict
from airflow.providers.amazon.aws.hooks.base_aws import AwsBaseHook
from uuid import uuid4
import warnings
import logging
import time

from airflow.exceptions import AirflowException
from airflow.models import BaseOperator

from cached_property import cached_property

log = logging.getLogger(__name__)
Context = NewType(Dict)


def waiter(
    get_state_callable: Callable,
    get_state_args: dict,
    parse_response: list,
    desired_state: set,
    failure_states: set,
    object_type: str,
    action: str,
    countdown: int | float | None = 25 * 60,
    check_interval_seconds: int = 60,
) -> None:
    """
    Will call get_state_callable until it reaches the desired_state or the failure_states.
    It will also time out if it waits longer than countdown seconds.

    PLEASE NOTE:  While not yet deprecated, we are moving away from this method
                  and encourage using the custom boto waiters as explained in
                  https://github.com/apache/airflow/tree/main/airflow/providers/amazon/aws/waiters

    :param get_state_callable: A callable to run until it returns True
    :param get_state_args: Arguments to pass to get_state_callable
    :param parse_response: Dictionary keys to extract state from response of get_state_callable
    :param desired_state: Wait until the getter returns this value
    :param failure_states: A set of states which indicate failure and should throw an
        exception if any are reached before the desired_state
    :param object_type: Used for the reporting string. What are you waiting for? (application, job, etc)
    :param action: Used for the reporting string. What action are you waiting for? (created, deleted, etc)
    :param countdown: Number of seconds the waiter should wait for the desired state before timing out.
        Defaults to 25 * 60 seconds. None = infinite.
    :param check_interval_seconds: Number of seconds waiter should wait before attempting
        to retry get_state_callable. Defaults to 60 seconds.
    """
    while True:
        state = get_state(get_state_callable(**get_state_args), parse_response)
        if state in desired_state:
            break
        if state in failure_states:
            raise AirflowException(f"{object_type.title()} reached failure state {state}.")

        if countdown is None:
            countdown = float("inf")

        if countdown > check_interval_seconds:
            countdown -= check_interval_seconds
            log.info("Waiting for %s to be %s.", object_type.lower(), action.lower())
            time.sleep(check_interval_seconds)
        else:
            message = f"{object_type.title()} still not {action.lower()} after the allocated time limit."
            log.error(message)
            raise RuntimeError(message)


def get_state(response, keys) -> str:
    value = response
    for key in keys:
        if value is not None:
            value = value.get(key, None)
    return value


class EmrServerlessHook(AwsBaseHook):
    """
    Interact with Amazon EMR Serverless.
    Provide thin wrapper around :py:class:`boto3.client("emr-serverless") <EMRServerless.Client>`.

    Additional arguments (such as ``aws_conn_id``) may be specified and
    are passed down to the underlying AwsBaseHook.

    .. seealso::
        - :class:`airflow.providers.amazon.aws.hooks.base_aws.AwsBaseHook`
    """

    JOB_INTERMEDIATE_STATES = {"PENDING", "RUNNING", "SCHEDULED", "SUBMITTED"}
    JOB_FAILURE_STATES = {"FAILED", "CANCELLING", "CANCELLED"}
    JOB_SUCCESS_STATES = {"SUCCESS"}
    JOB_TERMINAL_STATES = JOB_SUCCESS_STATES.union(JOB_FAILURE_STATES)

    APPLICATION_INTERMEDIATE_STATES = {"CREATING", "STARTING", "STOPPING"}
    APPLICATION_FAILURE_STATES = {"STOPPED", "TERMINATED"}
    APPLICATION_SUCCESS_STATES = {"CREATED", "STARTED"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["client_type"] = "emr-serverless"
        super().__init__(*args, **kwargs)

    @cached_property
    def conn(self):
        """Get the underlying boto3 EmrServerlessAPIService client (cached)"""
        return super().conn

    # This method should be replaced with boto waiters which would implement timeouts and backoff nicely.
    def waiter(
        self,
        get_state_callable: Callable,
        get_state_args: dict,
        parse_response: list,
        desired_state: set,
        failure_states: set,
        object_type: str,
        action: str,
        countdown: int = 25 * 60,
        check_interval_seconds: int = 60,
    ) -> None:
        """
        Will run the sensor until it turns True.

        :param get_state_callable: A callable to run until it returns True
        :param get_state_args: Arguments to pass to get_state_callable
        :param parse_response: Dictionary keys to extract state from response of get_state_callable
        :param desired_state: Wait until the getter returns this value
        :param failure_states: A set of states which indicate failure and should throw an
            exception if any are reached before the desired_state
        :param object_type: Used for the reporting string. What are you waiting for? (application, job, etc)
        :param action: Used for the reporting string. What action are you waiting for? (created, deleted, etc)
        :param countdown: Total amount of time the waiter should wait for the desired state
            before timing out (in seconds). Defaults to 25 * 60 seconds.
        :param check_interval_seconds: Number of seconds waiter should wait before attempting
            to retry get_state_callable. Defaults to 60 seconds.
        """
        warnings.warn(
            """This method is deprecated.
            Please use `airflow.providers.amazon.aws.utils.waiter.waiter`.""",
            DeprecationWarning,
            stacklevel=2,
        )
        waiter(
            get_state_callable=get_state_callable,
            get_state_args=get_state_args,
            parse_response=parse_response,
            desired_state=desired_state,
            failure_states=failure_states,
            object_type=object_type,
            action=action,
            countdown=countdown,
            check_interval_seconds=check_interval_seconds,
        )

    def get_state(self, response, keys) -> str:
        warnings.warn(
            """This method is deprecated.
            Please use `airflow.providers.amazon.aws.utils.waiter.get_state`.""",
            DeprecationWarning,
            stacklevel=2,
        )
        return get_state(response=response, keys=keys)


class EmrServerlessCreateApplicationOperator(BaseOperator):
    """
    Operator to create Serverless EMR Application

    .. seealso::
        For more information on how to use this operator, take a look at the guide:
        :ref:`howto/operator:EmrServerlessCreateApplicationOperator`

    :param release_label: The EMR release version associated with the application.
    :param job_type: The type of application you want to start, such as Spark or Hive.
    :param wait_for_completion: If true, wait for the Application to start before returning. Default to True.
        If set to False, ``waiter_countdown`` and ``waiter_check_interval_seconds`` will only be applied when
        waiting for the application to be in the ``CREATED`` state.
    :param client_request_token: The client idempotency token of the application to create.
      Its value must be unique for each request.
    :param config: Optional dictionary for arbitrary parameters to the boto API create_application call.
    :param aws_conn_id: AWS connection to use
    :param waiter_countdown: Total amount of time, in seconds, the operator will wait for
        the application to start. Defaults to 25 minutes.
    :param waiter_check_interval_seconds: Number of seconds between polling the state of the application.
        Defaults to 60 seconds.
    """

    def __init__(
        self,
        release_label: str,
        job_type: str,
        client_request_token: str = "",
        config: dict | None = None,
        wait_for_completion: bool = True,
        aws_conn_id: str = "aws_default",
        waiter_countdown: int = 25 * 60,
        waiter_check_interval_seconds: int = 60,
        **kwargs,
    ):
        self.aws_conn_id = aws_conn_id
        self.release_label = release_label
        self.job_type = job_type
        self.wait_for_completion = wait_for_completion
        self.kwargs = kwargs
        self.config = config or {}
        self.waiter_countdown = waiter_countdown
        self.waiter_check_interval_seconds = waiter_check_interval_seconds
        super().__init__(**kwargs)

        self.client_request_token = client_request_token or str(uuid4())

    @cached_property
    def hook(self) -> EmrServerlessHook:
        """Create and return an EmrServerlessHook."""
        return EmrServerlessHook(aws_conn_id=self.aws_conn_id)

    def execute(self, context: Context):
        response = self.hook.conn.create_application(
            clientToken=self.client_request_token,
            releaseLabel=self.release_label,
            type=self.job_type,
            **self.config,
        )
        application_id = response["applicationId"]

        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            raise AirflowException(f"Application Creation failed: {response}")

        self.log.info("EMR serverless application created: %s", application_id)

        # This should be replaced with a boto waiter when available.
        waiter(
            get_state_callable=self.hook.conn.get_application,
            get_state_args={"applicationId": application_id},
            parse_response=["application", "state"],
            desired_state={"CREATED"},
            failure_states=EmrServerlessHook.APPLICATION_FAILURE_STATES,
            object_type="application",
            action="created",
            countdown=self.waiter_countdown,
            check_interval_seconds=self.waiter_check_interval_seconds,
        )

        self.log.info("Starting application %s", application_id)
        self.hook.conn.start_application(applicationId=application_id)

        if self.wait_for_completion:
            # This should be replaced with a boto waiter when available.
            waiter(
                get_state_callable=self.hook.conn.get_application,
                get_state_args={"applicationId": application_id},
                parse_response=["application", "state"],
                desired_state={"STARTED"},
                failure_states=EmrServerlessHook.APPLICATION_FAILURE_STATES,
                object_type="application",
                action="started",
                countdown=self.waiter_countdown,
                check_interval_seconds=self.waiter_check_interval_seconds,
            )

        return application_id


class EmrServerlessStartJobOperator(BaseOperator):
    """
    Operator to start EMR Serverless job.

    .. seealso::
        For more information on how to use this operator, take a look at the guide:
        :ref:`howto/operator:EmrServerlessStartJobOperator`

    :param application_id: ID of the EMR Serverless application to start.
    :param execution_role_arn: ARN of role to perform action.
    :param job_driver: Driver that the job runs on.
    :param configuration_overrides: Configuration specifications to override existing configurations.
    :param client_request_token: The client idempotency token of the application to create.
      Its value must be unique for each request.
    :param config: Optional dictionary for arbitrary parameters to the boto API start_job_run call.
    :param wait_for_completion: If true, waits for the job to start before returning. Defaults to True.
        If set to False, ``waiter_countdown`` and ``waiter_check_interval_seconds`` will only be applied
        when waiting for the application be to in the ``STARTED`` state.
    :param aws_conn_id: AWS connection to use.
    :param name: Name for the EMR Serverless job. If not provided, a default name will be assigned.
    :param waiter_countdown: Total amount of time, in seconds, the operator will wait for
        the job finish. Defaults to 25 minutes.
    :param waiter_check_interval_seconds: Number of seconds between polling the state of the job.
        Defaults to 60 seconds.
    """

    template_fields: Sequence[str] = (
        "application_id",
        "execution_role_arn",
        "job_driver",
        "configuration_overrides",
    )

    def __init__(
        self,
        application_id: str,
        execution_role_arn: str,
        job_driver: dict,
        configuration_overrides: dict | None,
        client_request_token: str = "",
        config: dict | None = None,
        wait_for_completion: bool = True,
        aws_conn_id: str = "aws_default",
        name: str | None = None,
        waiter_countdown: int = 25 * 60,
        waiter_check_interval_seconds: int = 60,
        **kwargs,
    ):
        self.aws_conn_id = aws_conn_id
        self.application_id = application_id
        self.execution_role_arn = execution_role_arn
        self.job_driver = job_driver
        self.configuration_overrides = configuration_overrides
        self.wait_for_completion = wait_for_completion
        self.config = config or {}
        self.name = name or self.config.pop("name", f"emr_serverless_job_airflow_{uuid4()}")
        self.waiter_countdown = waiter_countdown
        self.waiter_check_interval_seconds = waiter_check_interval_seconds
        super().__init__(**kwargs)

        self.client_request_token = client_request_token or str(uuid4())

    @cached_property
    def hook(self) -> EmrServerlessHook:
        """Create and return an EmrServerlessHook."""
        return EmrServerlessHook(aws_conn_id=self.aws_conn_id)

    def execute(self, context: Context) -> dict:
        self.log.info("Starting job on Application: %s", self.application_id)

        app_state = self.hook.conn.get_application(applicationId=self.application_id)["application"]["state"]
        if app_state not in EmrServerlessHook.APPLICATION_SUCCESS_STATES:
            self.hook.conn.start_application(applicationId=self.application_id)

            waiter(
                get_state_callable=self.hook.conn.get_application,
                get_state_args={"applicationId": self.application_id},
                parse_response=["application", "state"],
                desired_state={"STARTED"},
                failure_states=EmrServerlessHook.APPLICATION_FAILURE_STATES,
                object_type="application",
                action="started",
                countdown=self.waiter_countdown,
                check_interval_seconds=self.waiter_check_interval_seconds,
            )

        response = self.hook.conn.start_job_run(
            clientToken=self.client_request_token,
            applicationId=self.application_id,
            executionRoleArn=self.execution_role_arn,
            jobDriver=self.job_driver,
            configurationOverrides=self.configuration_overrides,
            name=self.name,
            **self.config,
        )

        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            raise AirflowException(f"EMR serverless job failed to start: {response}")

        self.log.info("EMR serverless job started: %s", response["jobRunId"])
        if self.wait_for_completion:
            # This should be replaced with a boto waiter when available.
            waiter(
                get_state_callable=self.hook.conn.get_job_run,
                get_state_args={
                    "applicationId": self.application_id,
                    "jobRunId": response["jobRunId"],
                },
                parse_response=["jobRun", "state"],
                desired_state=EmrServerlessHook.JOB_SUCCESS_STATES,
                failure_states=EmrServerlessHook.JOB_FAILURE_STATES,
                object_type="job",
                action="run",
                countdown=self.waiter_countdown,
                check_interval_seconds=self.waiter_check_interval_seconds,
            )
        return response["jobRunId"]


class EmrServerlessDeleteApplicationOperator(BaseOperator):
    """
    Operator to delete EMR Serverless application

    .. seealso::
        For more information on how to use this operator, take a look at the guide:
        :ref:`howto/operator:EmrServerlessDeleteApplicationOperator`

    :param application_id: ID of the EMR Serverless application to delete.
    :param wait_for_completion: If true, wait for the Application to start before returning. Default to True
    :param aws_conn_id: AWS connection to use
    :param waiter_countdown: Total amount of time, in seconds, the operator will wait for
        the application be deleted. Defaults to 25 minutes.
    :param waiter_check_interval_seconds: Number of seconds between polling the state of the application.
        Defaults to 60 seconds.
    """

    template_fields: Sequence[str] = ("application_id",)

    def __init__(
        self,
        application_id: str,
        wait_for_completion: bool = True,
        aws_conn_id: str = "aws_default",
        waiter_countdown: int = 25 * 60,
        waiter_check_interval_seconds: int = 60,
        **kwargs,
    ):
        self.aws_conn_id = aws_conn_id
        self.application_id = application_id
        self.wait_for_completion = wait_for_completion
        self.waiter_countdown = waiter_countdown
        self.waiter_check_interval_seconds = waiter_check_interval_seconds
        super().__init__(**kwargs)

    @cached_property
    def hook(self) -> EmrServerlessHook:
        """Create and return an EmrServerlessHook."""
        return EmrServerlessHook(aws_conn_id=self.aws_conn_id)

    def execute(self, context: Context) -> None:
        self.log.info("Stopping application: %s", self.application_id)
        self.hook.conn.stop_application(applicationId=self.application_id)

        # This should be replaced with a boto waiter when available.
        waiter(
            get_state_callable=self.hook.conn.get_application,
            get_state_args={
                "applicationId": self.application_id,
            },
            parse_response=["application", "state"],
            desired_state=EmrServerlessHook.APPLICATION_FAILURE_STATES,
            failure_states=set(),
            object_type="application",
            action="stopped",
            countdown=self.waiter_countdown,
            check_interval_seconds=self.waiter_check_interval_seconds,
        )

        self.log.info("Deleting application: %s", self.application_id)
        response = self.hook.conn.delete_application(applicationId=self.application_id)

        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            raise AirflowException(f"Application deletion failed: {response}")

        if self.wait_for_completion:
            # This should be replaced with a boto waiter when available.
            waiter(
                get_state_callable=self.hook.conn.get_application,
                get_state_args={"applicationId": self.application_id},
                parse_response=["application", "state"],
                desired_state={"TERMINATED"},
                failure_states=EmrServerlessHook.APPLICATION_FAILURE_STATES,
                object_type="application",
                action="deleted",
                countdown=self.waiter_countdown,
                check_interval_seconds=self.waiter_check_interval_seconds,
            )

        self.log.info("EMR serverless application deleted")
