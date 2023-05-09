/*
 * Copyright (c) 2023 Airbyte, Inc., all rights reserved.
 */

package io.airbyte.integrations.source.postgres;

import io.airbyte.commons.json.Jsons;
import io.airbyte.protocol.models.AirbyteStreamNameNamespacePair;
import io.airbyte.protocol.models.v0.AirbyteStateMessage;
import io.airbyte.protocol.models.v0.AirbyteStateMessage.AirbyteStateType;
import io.airbyte.protocol.models.v0.AirbyteStreamState;
import io.airbyte.protocol.models.v0.StreamDescriptor;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class XminStateManager {

  private static final Logger LOGGER = LoggerFactory.getLogger(XminStateManager.class);

  private final Map<AirbyteStreamNameNamespacePair, XminStatus> pairToXminStatus;

  private final static AirbyteStateMessage EMPTY_STATE = new AirbyteStateMessage()
      .withType(AirbyteStateType.STREAM)
      .withStream(new AirbyteStreamState());

  XminStateManager(final List<AirbyteStateMessage> stateMessages) {
    pairToXminStatus = createPairToXminStatusMap(stateMessages);
  }

  private static Map<AirbyteStreamNameNamespacePair, XminStatus> createPairToXminStatusMap(final List<AirbyteStateMessage> stateMessages) {
    final Map<AirbyteStreamNameNamespacePair, XminStatus> localMap = new HashMap<>();
    if (stateMessages != null) {
      for (final AirbyteStateMessage stateMessage : stateMessages) {
        // A reset causes the default state to be an empty legacy state, so we have to ignore those messages. 
        if (stateMessage.getType() == AirbyteStateType.STREAM && !stateMessage.equals(EMPTY_STATE)) {
          LOGGER.info("State message: " + stateMessage);
          final StreamDescriptor streamDescriptor = stateMessage.getStream().getStreamDescriptor();
          final AirbyteStreamNameNamespacePair pair = new AirbyteStreamNameNamespacePair(streamDescriptor.getName(), streamDescriptor.getNamespace());
          final XminStatus xminStatus = Jsons.object(stateMessage.getStream().getStreamState(), XminStatus.class);
          localMap.put(pair, xminStatus);
        }
      }
    }
    return localMap;
  }

  public XminStatus getXminStatus(final AirbyteStreamNameNamespacePair pair) {
    return pairToXminStatus.get(pair);
  }

}
