# -*- coding: utf-8 -*-
import datetime

from pymysqlreplication.event import GtidEvent
from pymysqlreplication.event import QueryEvent

import mock
import pytest

from replication_handler.components.simple_binlog_stream_reader_wrapper import SimpleBinlogStreamReaderWrapper
from replication_handler.util.misc import DataEvent
from replication_handler.util.misc import ReplicationHandlerEvent
from replication_handler.util.position import GtidPosition
from replication_handler.util.position import LogPosition


class TestSimpleBinlogStreamReaderWrapper(object):

    @pytest.yield_fixture
    def patch_stream(self):
        with mock.patch(
            'replication_handler.components.simple_binlog_stream_reader_wrapper.LowLevelBinlogStreamReaderWrapper'
        ) as mock_stream:
            yield mock_stream

    @pytest.yield_fixture
    def patch_sensu(self):
        with mock.patch(
            'replication_handler.components.simple_binlog_stream_reader_wrapper.pysensu_yelp'
        ) as mock_sensu:
            yield mock_sensu

    @pytest.yield_fixture
    def patch_time(self):
        with mock.patch(
            'replication_handler.components.simple_binlog_stream_reader_wrapper.datetime'
        ) as mock_time:
            mock_time.datetime.now.return_value = datetime.datetime(2015, 10, 21, 12, 6, 27)
            yield mock_time

    def test_yield_events_when_gtid_enabled(self, patch_stream):
        gtid_event_0 = mock.Mock(spec=GtidEvent, gtid="sid:11")
        query_event_0 = mock.Mock(spec=QueryEvent)
        query_event_1 = mock.Mock(spec=QueryEvent)
        gtid_event_1 = mock.Mock(spec=GtidEvent, gtid="sid:12")
        data_event_0 = mock.Mock(spec=DataEvent)
        data_event_1 = mock.Mock(spec=DataEvent)
        data_event_2 = mock.Mock(spec=DataEvent)
        event_list = [
            gtid_event_0,
            query_event_0,
            data_event_0,
            data_event_1,
            data_event_2,
            gtid_event_1,
            query_event_1,
        ]
        patch_stream.return_value.peek.side_effect = event_list
        patch_stream.return_value.pop.side_effect = event_list
        # set offset to 1, meaning we want to skip event at offset 0
        stream = SimpleBinlogStreamReaderWrapper(
            GtidPosition(
                gtid="sid:10",
                offset=1
            ),
            gtid_enabled=True
        )
        results = [
            ReplicationHandlerEvent(
                event=data_event_1,
                position=GtidPosition(gtid="sid:11", offset=2)
            ),
            ReplicationHandlerEvent(
                event=data_event_2,
                position=GtidPosition(gtid="sid:11", offset=3)
            ),
            ReplicationHandlerEvent(
                event=query_event_1,
                position=GtidPosition(gtid="sid:12", offset=0)
            )
        ]
        for replication_event, result in zip(stream, results):
            assert replication_event.event == result.event
            assert replication_event.position.gtid == result.position.gtid
            assert replication_event.position.offset == result.position.offset

    def test_yield_event_with_heartbeat_event(self, patch_stream, patch_sensu, patch_time):
        stream, results = self._setup_stream_and_expected_result(patch_stream)
        assert patch_sensu.send_event.call_count == 0
        for replication_event, result in zip(stream, results):
            assert replication_event.event == result.event
            assert replication_event.position.log_pos == result.position.log_pos
            assert replication_event.position.log_file == result.position.log_file
            assert replication_event.position.offset == result.position.offset
            assert replication_event.position.hb_serial == result.position.hb_serial
            assert replication_event.position.hb_timestamp == result.position.hb_timestamp

    def test_heartbeat_event_trigger_sensu(self, patch_stream, patch_sensu, patch_time):
        # Make the time difference heartbeat timestamp and fake real time more than 10 min.
        patch_time.datetime.now.return_value = datetime.datetime(2015, 10, 21, 13, 6, 27)
        stream, _ = self._setup_stream_and_expected_result(patch_stream)
        stream.next()
        assert patch_sensu.send_event.call_count == 1

    def _setup_stream_and_expected_result(self, patch_stream):
        log_pos = 10
        log_file = "binlog.001"
        row = {"after_values": {"serial": 123, "timestamp": "2015-10-21 12:05:27"}}
        heartbeat_event = mock.Mock(
            spec=DataEvent,
            schema='yelp_heartbeat',
            log_pos=log_pos,
            log_file=log_file,
            row=row
        )
        data_event_0 = mock.Mock(spec=DataEvent, table="business", schema="yelp")
        data_event_1 = mock.Mock(spec=DataEvent, table="business", schema="yelp")
        data_event_2 = mock.Mock(spec=DataEvent, table="business", schema="yelp")
        event_list = [
            heartbeat_event,
            data_event_0,
            data_event_1,
            data_event_2,
        ]
        patch_stream.return_value.peek.side_effect = event_list
        patch_stream.return_value.pop.side_effect = event_list
        stream = SimpleBinlogStreamReaderWrapper(
            LogPosition(
                log_pos=log_pos,
                log_file=log_file,
                offset=0
            ),
            gtid_enabled=False,
        )
        # Since the offset is 0, so the result should start offset 1, and skip
        # data_event_0 which is at offset 0.
        results = [
            ReplicationHandlerEvent(
                event=data_event_1,
                position=LogPosition(
                    log_pos=log_pos,
                    log_file=log_file,
                    offset=1,
                    hb_serial=123,
                    hb_timestamp="2015-10-21 12:05:27",
                )
            ),
            ReplicationHandlerEvent(
                event=data_event_2,
                position=LogPosition(
                    log_pos=log_pos,
                    log_file=log_file,
                    offset=2,
                    hb_serial=123,
                    hb_timestamp="2015-10-21 12:05:27",
                )
            )
        ]
        return stream, results
