"""Voice mode: Pipecat belt around the SAME handle_turn used in text mode."""

import asyncio  # lets slow work run without freezing audio
import os  # read API keys from environment

from dotenv import load_dotenv  # load keys from .env
from loguru import logger  # nicer log prints (comes with Pipecat)

from pipecat.audio.vad.silero import (
    SileroVADAnalyzer,
)  # concept 3: VAD, hears when you stop
from pipecat.frames.frames import (  # concept 4: the items on the belt
    LLMContextFrame,  # "caller finished a turn, here's the conversation"
    LLMFullResponseStartFrame,  # "bot reply starting"
    LLMFullResponseEndFrame,  # "bot reply finished"
    LLMTextFrame,  # the reply text itself
    TTSSpeakFrame,  # "say this exact sentence" (used for the greeting)
)
from pipecat.pipeline.pipeline import Pipeline  # concept 4: the belt
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,  # collects your words into one turn
)
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
)  # base class for a station
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport  # concept 5: browser connection
from pipecat.services.deepgram.stt import DeepgramSTTService  # concept 1: STT
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService  # concept 2: TTS
from pipecat.transports.base_transport import TransportParams
from pipecat.workers.runner import WorkerRunner

from agent.core import handle_turn, new_session, save_log  # YOUR agent, unchanged
from agent.db import init_db

load_dotenv(override=True)


class NightShiftBrain(FrameProcessor):
    """Our station. Replaces Pipecat's generic LLM with the same handle_turn text mode uses."""

    def __init__(self, conn, session):
        super().__init__()  # required setup for any Pipecat station
        self.conn = conn  # the database
        self.session = session  # memory for this call (gates read it)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)  # required first line

        # Not "caller finished talking"? Not our job: pass it down the belt.
        # (speculation = Pipecat guessing early; ignore those, only act on real turns)
        if not isinstance(frame, LLMContextFrame) or frame.speculation:
            await self.push_frame(frame, direction)
            return

        # Grab the caller's latest words from the conversation
        user_msgs = [m for m in frame.context.get_messages() if m.get("role") == "user"]
        content = user_msgs[-1]["content"] if user_msgs else ""
        if isinstance(
            content, list
        ):  # sometimes it's a list of pieces; join the text ones
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )

        # Run YOUR agent. to_thread = do it on the side, so audio keeps flowing meanwhile
        reply = await asyncio.to_thread(handle_turn, self.conn, self.session, content)

        # Put the reply on the belt: start signal, the text, end signal. ElevenLabs speaks it.
        await self.push_frame(LLMFullResponseStartFrame())
        await self.push_frame(LLMTextFrame(reply))
        await self.push_frame(LLMFullResponseEndFrame())


async def run_bot(transport, runner_args: RunnerArguments):
    # ---- start of call: same as chat.py ----
    conn = init_db()  # fresh fake shop
    session = new_session()  # blank call memory

    # ---- the stations ----
    stt = DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        settings=DeepgramSTTService.Settings(numerals=True),
    )  # voice -> text
    tts = ElevenLabsTTSService(  # text -> voice
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(
            voice="EXAVITQu4vr4xnSDxMaL"
        ),  # "Sarah, reassuring"
    )
    brain = NightShiftBrain(conn, session)  # YOUR agent

    # Collects the caller's words; VAD decides when their turn is over
    context = LLMContext()
    user_turn, bot_turn = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())
    )

    # ---- the belt, in order ----
    pipeline = Pipeline(
        [
            transport.input(),  # mic audio in (from browser)
            stt,  # Deepgram: audio -> text
            user_turn,  # VAD: wait until caller stops, then send the turn
            brain,  # handle_turn: gates, tools, Gemini
            tts,  # ElevenLabs: reply -> audio
            transport.output(),  # audio out (to browser speaker)
            bot_turn,  # remember what the bot said
        ]
    )

    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True))
    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    # ---- events ----
    @transport.event_handler("on_client_connected")  # you clicked Connect
    async def on_connect(transport, client):
        await worker.queue_frames(
            [
                TTSSpeakFrame(
                    "Lakeside Plumbing and Heating, after-hours line. What's going on?"
                )
            ]
        )

    @transport.event_handler("on_client_disconnected")  # you hung up
    async def on_disconnect(transport, client):
        logger.info(f"Log saved: {save_log(session)}")
        await runner.cancel()

    await runner.run()  # start the belt; runs until hang-up


async def bot(runner_args: RunnerArguments):
    """Pipecat's runner calls this when you click Connect in the browser."""
    transport = await create_transport(
        runner_args,
        {
            "webrtc": lambda: TransportParams(
                audio_in_enabled=True, audio_out_enabled=True
            ),  # browser mic + speaker
        },
    )
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()  # starts a local web server with the Connect page
