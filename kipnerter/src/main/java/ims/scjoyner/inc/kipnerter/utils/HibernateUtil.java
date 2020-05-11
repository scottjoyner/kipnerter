package ims.scjoyner.inc.kipnerter.utils;

import org.hibernate.HibernateException;
import org.hibernate.Session;
import org.hibernate.SessionFactory;
import org.hibernate.cfg.Configuration;

/**
 * A utility class for setting up the Hibernate SessionFactory
 *
 * @author Elizabeth Gilbert
 * @author Kai Presler-Marshall
 */
public class HibernateUtil {

    /**
     * SeesionFactory used
     */
    private static SessionFactory sessionFactory = buildSessionFactory();

    /**
     * Creates a SessionFactory
     *
     * @return SessioNFactory that was built
     */
    private static SessionFactory buildSessionFactory () {
        try {
            // Create the SessionFactory from hibernate.cfg.xml
            final Configuration c = new Configuration();
            c.configure();

            c.setProperty( "hibernate.connection.url", DBUtil.getUrl() );
            c.setProperty( "hibernate.connection.username", DBUtil.getUsername() );
            c.setProperty( "hibernate.connection.password", DBUtil.getPassword() );

            return c.buildSessionFactory();
            // return new Configuration().configure().buildSessionFactory();
        }
        catch ( final HibernateException ex ) {
            // Make sure you log the exception, as it might be swallowed
            System.err.println( "Initial SessionFactory creation failed." + ex );
            throw new ExceptionInInitializerError( ex );
        }
    }

    /**
     * Retrieves the SessionFactory generated
     *
     * @return sessionFactory that was generated
     */
    private static SessionFactory getSessionFactory () {
        return sessionFactory;
    }

    /**
     * Retrieve a Session from Hibernate. Wrapper code to avoid boilerplate.
     *
     * @return The Session retrieved from the SessionFactory
     * @throws HibernateException
     *             If a session cannot be opened
     */
    public static Session openSession () throws HibernateException {
        return getSessionFactory().openSession();
    }

    /**
     * Close the SessionFactory
     */
    public static void shutdown () {
        // Close caches and connection pools
        if ( null != sessionFactory ) {
            sessionFactory.close();
        }
    }
}
