package ims.scjoyner.inc.kipnerter.adapters;

import java.sql.Timestamp;
import java.time.ZoneId;
import java.time.ZonedDateTime;

import javax.persistence.AttributeConverter;
import javax.persistence.Converter;

/**
 * ZonedDateTime converter for database storage. This provides it to be
 * readable in the database.
 * 
 * @author Matt Dzwonczyk
 */
@Converter
public class ZonedDateTimeAttributeConverter implements AttributeConverter<ZonedDateTime, Timestamp> {

    /**
     * Converts the ZonedDateTime to a database field.
     * @param zonedDateTime The ZonedDateTime to convert.
     * @return The ZonedDateTime as a Timestamp instance.
     */
    public Timestamp convertToDatabaseColumn(ZonedDateTime zonedDateTime) {
        return zonedDateTime == null ? null : Timestamp.from( zonedDateTime.toInstant() );
    }

    /**
     * Converts the database Timestamp to a ZonedDateTime object.
     * @param sqlTimestamp The Timestamp to convert.
     * @return The Timestamp as a ZonedDateTime instance.
     */
    public ZonedDateTime convertToEntityAttribute(Timestamp sqlTimestamp) {
        return sqlTimestamp == null ? null : sqlTimestamp.toInstant().atZone( ZoneId.systemDefault() );
    }

}