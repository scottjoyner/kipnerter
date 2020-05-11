package ims.scjoyner.inc.kipnerter.utils;

import java.text.ParseException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import org.hibernate.boot.MetadataSources;
import org.hibernate.boot.registry.StandardServiceRegistryBuilder;
import org.hibernate.boot.spi.MetadataImplementor;
import org.hibernate.tool.hbm2ddl.SchemaExport;


import ims.scjoyner.inc.kipnerter.models.enums.Gender;
import ims.scjoyner.inc.kipnerter.models.enums.Role;
import ims.scjoyner.inc.kipnerter.models.enums.State;
import ims.scjoyner.inc.kipnerter.models.persistent.Personnel;
import ims.scjoyner.inc.kipnerter.models.persistent.User;

/**
 * Newly revamped Test Data Generator. This class is used to generate database
 * records for the various different types of persistent objects that exist in
 * the system. Takes advantage of Hibernate persistence. To use, instantiate the
 * type of object in question, set all of its parameters, and then call the
 * save() method on the object.
 *
 * @author Kai Presler-Marshall
 *
 */
public class HibernateDataGenerator {

    /**
     * Starts the data generator program.
     *
     * @param args
     *            command line arguments
     * @throws ParseException
     * @throws NumberFormatException
     */
    public static void main ( final String args[] ) throws NumberFormatException, ParseException {
        refreshDB();

        System.exit( 0 );
        return;
    }

    /**
     * Generate sample users for the iTrust2 system.
     *
     * @throws ParseException
     * @throws NumberFormatException
     */
    public static void refreshDB () throws NumberFormatException, ParseException {
        // using the config to drop/create taken from here:
        // https://stackoverflow.com/questions/20535423/how-to-manually-invoke-create-drop-from-jpa-on-hibernate
        // how to actually generate the schemaexport taken from here:
        // http://www.javarticles.com/2015/06/generating-database-schema-using-hibernate.html

        final StandardServiceRegistryBuilder ssrb = new StandardServiceRegistryBuilder();
        ssrb.configure( "/hibernate.cfg.xml" );
        ssrb.applySetting( "hibernate.connection.url", DBUtil.getUrl() );
        ssrb.applySetting( "hibernate.connection.username", DBUtil.getUsername() );
        ssrb.applySetting( "hibernate.connection.password", DBUtil.getPassword() );
        final SchemaExport export = new SchemaExport(
                (MetadataImplementor) new MetadataSources( ssrb.build() ).buildMetadata() );
        export.drop( true, true );
        export.create( true, true );

        generateUsers();
    }

    /**
     * Generate sample users for the iTrust2 system.
     */
    public static void generateUsers () {
        final User hcp = new User( "scjoyner", "$2a$10$EblZqNptyYvcLm/VwDCVAuBjzZOI7khzdyGPBr08PpIi0na624b8.", Role.ROLE_ADMIN,
                1 );
        hcp.save();

        final Personnel p = new Personnel();
        p.setSelf( hcp );
        p.setFirstName( "Scott" );
        p.setLastName( "Joyner" );
        p.setEmail( "kipnerter@gmail.com" );
        p.setAddress1( "1540 Norman Pl." );
        p.setCity( "Raleigh" );
        p.setState( State.NC );
        p.setZip( "28277" );
        p.setPhone( "704-799-5781" );
        p.save();

        final User customer = new User( "customer", "$2a$10$EblZqNptyYvcLm/VwDCVAuBjzZOI7khzdyGPBr08PpIi0na624b8.",
                Role.ROLE_CUSTOMER, 1 );
        customer.save();

        final User admin = new User( "admin", "$2a$10$EblZqNptyYvcLm/VwDCVAuBjzZOI7khzdyGPBr08PpIi0na624b8.",
                Role.ROLE_ADMIN, 1 );
        admin.save();

        
        // generate users for testing password change & reset
        for ( int i = 1; i <= 5; i++ ) {
            final User pwtestuser = new User( "pwtestuser" + i,
                    "$2a$10$EblZqNptyYvcLm/VwDCVAuBjzZOI7khzdyGPBr08PpIi0na624b8.", Role.ROLE_CUSTOMER, 1 );
            pwtestuser.save();
        }

        final User lockoutUser = new User( "lockoutUser",
                "$2a$10$EblZqNptyYvcLm/VwDCVAuBjzZOI7khzdyGPBr08PpIi0na624b8.", Role.ROLE_CUSTOMER, 1 );
        lockoutUser.save();

        final User lockoutUser2 = new User( "lockoutUser2",
                "$2a$10$EblZqNptyYvcLm/VwDCVAuBjzZOI7khzdyGPBr08PpIi0na624b8.", Role.ROLE_CUSTOMER, 1 );
        lockoutUser2.save();

        final User knightSolaire = new User( "knightSolaire",
                "$2a$10$EblZqNptyYvcLm/VwDCVAuBjzZOI7khzdyGPBr08PpIi0na624b8.", Role.ROLE_CUSTOMER, 1 );
        knightSolaire.save();
        final Personnel kniSolai = new Personnel();
        kniSolai.setSelf( knightSolaire );
        kniSolai.setFirstName( "Knight" );
        kniSolai.setLastName( "Solaire" );
        kniSolai.save();

        final User labTech = new User( "labtech", "$2a$10$EblZqNptyYvcLm/VwDCVAuBjzZOI7khzdyGPBr08PpIi0na624b8.",
                Role.ROLE_CUSTOMER, 1 );
        labTech.save();
        final Personnel labTechPerson = new Personnel();
        labTechPerson.setSelf( labTech );
        labTechPerson.setFirstName( "Lab" );
        labTechPerson.setLastName( "Technician" );
        labTechPerson.save();
    }
}
