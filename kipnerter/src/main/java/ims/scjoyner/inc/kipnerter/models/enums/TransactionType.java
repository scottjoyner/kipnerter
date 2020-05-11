package ims.scjoyner.inc.kipnerter.models.enums;

public enum TransactionType {
	/**
     * Failed login
     */
    LOGIN_FAILURE ( 1, "Failed login", true ),
    /**
     * Successful login
     */
    LOGIN_SUCCESS ( 2, "Successful login", true ),
    /**
     * User logged out
     */
    LOGOUT ( 3, "Logged Out", true ),
    /**
     * User locked out of system (temporary)
     */
    USER_LOCKOUT ( 4, "User Locked Out", true ),
    /**
     * IP locked out of system (temporary)
     */
    IP_LOCKOUT ( 5, "IP Locked Out", true ),
    /**
     * User banned
     */
    USER_BANNED ( 6, "User Banned", true ),
    /**
     * IP Banned
     */
    IP_BANNED ( 7, "IP Banned", true ),
    /**
     * New User created
     */
    CREATE_USER ( 100, "New user created", true ),
    /**
     * User was viewed
     */
    VIEW_USER ( 101, "Single user viewed", false ),
    /**
     * Multiple users viewed
     */
    VIEW_USERS ( 102, "List of users viewed", false ),
    /**
     * User deleted
     */
    DELETE_USER ( 103, "User deleted", false ),
    /**
     * User changed/updated
     */
    UPDATE_USER ( 104, "User updated", false ), 
    /**
     * Created a new lockout email from a failed request
     */
    CREATE_LOCKOUT_EMAIL (105, "Lockout Email Created", false ), 
    /**
     * Missing email log
     */
    CREATE_MISSING_EMAIL_LOG(106, "Missing Email Created", false), 
    /**
     * modify user demographics
     */
    EDIT_DEMOGRAPHICS(107, "Modified User Demographics", false), 
    /**
     * View User Demographics
     */
    VIEW_DEMOGRAPHICS(108, "Viewed User Demographics", false), 
    /**
     * Created new demographics
     */
    CREATE_DEMOGRAPHICS(109, "Created new user demographics", true), 
    /**
     * View a users log entrys
     */
    VIEW_USER_LOG(110, "View user log", false), 
    /**
     * Updated Password
     */
    PASSWORD_UPDATE_SUCCESS(111, "Password Updated", true), 
    /**
     * Create Password Change email
     */
    CREATE_PW_CHANGE_EMAIL(112, "Password created for email", true), 
    /**
     * Failed to update Password
     */
    PASSWORD_UPDATE_FAILURE(113, "Failed to update password", true);
	
	
	
    
    /**
     * Creates a TransactionType for logging events
     *
     * @param code
     *            Code of the event
     * @param description
     *            Description of the event that occurred
     * @param patientViewable
     *            Whether this logged event can be viewed by the patient
     *            involved
     */
    private TransactionType ( final int code, final String description, final boolean adminViewable ) {
        this.code = code;
        this.description = description;
        this.adminView = adminViewable;
    }

    /**
     * Code of the TransactionType, from the iTrust2 wiki.
     */
    private int     code;
    /**
     * Description of the event
     */
    private String  description;
    /**
     * Whether the patient can view the event
     */
    private boolean adminView;

    /**
     * Retrieves the code of this TransactionType
     *
     * @return Code of the event
     */
    public int getCode () {
        return code;
    }

    /**
     * Description of this TransactionType event
     *
     * @return Description of the event
     */
    public String getDescription () {
        return description;
    }

    /**
     * Retrieves if the Patient can view this event
     *
     * @return Patient viewable or not
     */
    public boolean isAdminViewable () {
        return adminView;
    }
}
