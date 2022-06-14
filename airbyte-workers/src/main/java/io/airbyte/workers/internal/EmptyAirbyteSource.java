/*
 * Copyright (c) 2022 Airbyte, Inc., all rights reserved.
 */

package io.airbyte.workers.internal;

import com.fasterxml.jackson.databind.JsonNode;
import io.airbyte.commons.json.Jsons;
import io.airbyte.config.ResetSourceConfiguration;
import io.airbyte.config.StreamDescriptor;
import io.airbyte.config.WorkerSourceConfig;
import io.airbyte.protocol.models.AirbyteMessage;
import io.airbyte.protocol.models.AirbyteMessage.Type;
import io.airbyte.protocol.models.AirbyteStateMessage;
import io.airbyte.protocol.models.AirbyteStateMessage.AirbyteStateType;
import io.airbyte.protocol.models.AirbyteStreamState;
import io.airbyte.protocol.models.StateMessageHelper;
import io.vavr.control.Either;
import java.nio.file.Path;
import java.util.List;
import java.util.Optional;
import java.util.Stack;
import java.util.concurrent.atomic.AtomicBoolean;
import lombok.extern.slf4j.Slf4j;

/**
 * This source will never emit any messages. It can be used in cases where that is helpful (hint:
 * reset connection jobs).
 */
@Slf4j
public class EmptyAirbyteSource implements AirbyteSource {

  private final AtomicBoolean hasEmittedState;
  private final Stack<StreamDescriptor> streamDescriptors = new Stack<>();
  private boolean isPartialReset;
  private boolean isStarted = false;

  public EmptyAirbyteSource() {
    hasEmittedState = new AtomicBoolean();
  }

  @Override
  public void start(final WorkerSourceConfig sourceConfig, final Path jobRoot) throws Exception {

    try {
      if (sourceConfig == null || sourceConfig.getSourceConnectionConfiguration() == null) {
        isPartialReset = false;
      } else {
        ResetSourceConfiguration sourceConfiguration = Jsons.object(sourceConfig.getSourceConnectionConfiguration(), ResetSourceConfiguration.class);
        streamDescriptors.addAll(sourceConfiguration.getStreamsToReset());
        if (streamDescriptors.isEmpty()) {
          isPartialReset = false;
        } else {
          Either<JsonNode, List<AirbyteStateMessage>> eitherState = StateMessageHelper.getTypeState(sourceConfig.getState().getState());
          if (eitherState.isLeft()) {
            log.error("The state is not compatible with a partial reset that  have been requested");
            throw new IllegalStateException("Legacy state for a partial reset");
          }

          if (eitherState.isRight()) {

          }
          isPartialReset = true;
        }
      }
    } catch (IllegalArgumentException e) {
      // No op, the new format is not supported
      isPartialReset = false;
    }
    isStarted = true;
  }

  // always finished. it has no data to send.
  @Override
  public boolean isFinished() {
    return hasEmittedState.get();
  }

  @Override
  public int getExitValue() {
    return 0;
  }

  @Override
  public Optional<AirbyteMessage> attemptRead() {
    if (!isStarted) {
      throw new IllegalStateException("The empty source has not been started.");
    }

    if (isPartialReset) {
      if (!streamDescriptors.isEmpty()) {
        StreamDescriptor streamDescriptor = streamDescriptors.pop();
        AirbyteMessage responseMessage = new AirbyteMessage()
            .withState(
                new AirbyteStateMessage()
                    .withStream(new AirbyteStreamState()
                        .withStreamDescriptor(
                            new io.airbyte.protocol.models.StreamDescriptor()
                                .withName(streamDescriptor.getName())
                                .withNamespace(streamDescriptor.getNamespace()))
                        .withStreamState(null)));
        return Optional.of(responseMessage);
      } else {
        return Optional.empty();
      }
    } else {
      if (!hasEmittedState.get()) {
        hasEmittedState.compareAndSet(false, true);
        return Optional.of(new AirbyteMessage().withType(Type.STATE).withState(new AirbyteStateMessage().withStateType(AirbyteStateType.LEGACY).withData(Jsons.emptyObject())));
      } else {
        return Optional.empty();
      }
    }
  }

  @Override
  public void close() throws Exception {
    // no op.
  }

  @Override
  public void cancel() throws Exception {
    // no op.
  }

}
